"""Local map UI for labeling independent validation points against 2020 imagery."""
from __future__ import annotations

import csv
import json
import threading
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import ee

from taoyuan_gee.pipeline import study_area
from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "results" / "validation_candidates_2020.csv"
LABELS_PATH = ROOT / "results" / "validation_labels_2020.json"
REVIEW_QUEUE_PATH = ROOT / "results" / "validation_review_queue_2020.json"
CONFIG_PATH = ROOT / "pipeline_config.json"
LOCK = threading.Lock()
CLASS_NAMES = {0: "水体", 1: "植被", 2: "农地", 3: "裸地", 4: "建成区"}


def sentinel_2020(roi: ee.Geometry) -> ee.Image:
    def mask(image: ee.Image) -> ee.Image:
        scl = image.select("SCL")
        clear = (
            scl.neq(1)
            .And(scl.neq(3))
            .And(scl.neq(8))
            .And(scl.neq(9))
            .And(scl.neq(10))
            .And(scl.neq(11))
        )
        return image.updateMask(clear).divide(10000).copyProperties(image, ["system:time_start"])

    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi)
        .filterDate("2020-01-01", "2021-01-01")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        .map(mask)
        .median()
        .clip(roi)
    )


def read_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_labels() -> dict[str, dict]:
    if not LABELS_PATH.exists():
        return {}
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))


def read_review_queue() -> set[str]:
    if not REVIEW_QUEUE_PATH.exists():
        return set()
    data = json.loads(REVIEW_QUEUE_PATH.read_text(encoding="utf-8"))
    return set(data.get("review_queue", []))


def write_labels(labels: dict[str, dict]) -> None:
    temp = LABELS_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(LABELS_PATH)


def public_rows() -> list[dict]:
    rows = read_rows()
    labels = read_labels()
    review_queue = read_review_queue()
    return [
        {
            "candidate_id": row["candidate_id"],
            "longitude": float(row["longitude"]),
            "latitude": float(row["latitude"]),
            "reference_class": int(labels.get(row["candidate_id"], {}).get("reference_class", row["reference_class"])),
            "review_status": labels.get(row["candidate_id"], {}).get("review_status", row["review_status"]),
            "audit_review_required": (
                row["candidate_id"] in review_queue
                and not labels.get(row["candidate_id"], {}).get("box_reviewed", False)
            ),
        }
        for row in rows
    ]


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>桃园 2020 验证点判读</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,"Microsoft YaHei",sans-serif;background:#111827;color:#f9fafb}
#map{position:fixed;inset:0 340px 0 0}.panel{position:fixed;right:0;top:0;bottom:0;width:340px;padding:22px;background:#111827;overflow:auto}
h1{font-size:20px;margin:0 0 8px}.muted{color:#9ca3af;font-size:13px;line-height:1.5}.progress{height:10px;background:#374151;border-radius:8px;overflow:hidden;margin:14px 0}.bar{height:100%;background:#22c55e}
.point{font-size:22px;font-weight:700;margin:18px 0 5px}.classbtn{display:block;width:100%;padding:12px;margin:8px 0;border:0;border-radius:9px;color:#fff;font-size:16px;font-weight:700;cursor:pointer;text-align:left}
.c0{background:#2563eb}.c1{background:#15803d}.c2{background:#ca8a04}.c3{background:#a16207}.c4{background:#dc2626}.cmix{background:#7c3aed}.nav{display:flex;gap:8px;margin-top:15px}.nav button,.secondary{flex:1;padding:10px;border:1px solid #4b5563;border-radius:8px;background:#1f2937;color:#fff;cursor:pointer}.secondary{width:100%;margin-top:8px}.done{color:#86efac}.warning{color:#fde68a}.leaflet-control-layers{color:#111827}
@media(max-width:800px){#map{inset:0 0 390px 0}.panel{top:auto;left:0;width:100%;height:390px;padding:14px}.classbtn{display:inline-block;width:48%;margin:4px 1%}}
</style></head><body><div id="map"></div><aside class="panel">
<h1>桃园 2020 验证点判读</h1><div class="muted">彩色方框就是完整的30 m × 30 m像元。判断方框内占比最大的地表；模型答案已隐藏。</div>
<div class="progress"><div class="bar" id="bar"></div></div><div id="status" class="done"></div>
<div class="point" id="point"></div><div class="muted" id="coords"></div>
<button class="classbtn c0" onclick="label(0)">0　水体</button><button class="classbtn c1" onclick="label(1)">1　植被</button>
<button class="classbtn c2" onclick="label(2)">2　农地</button><button class="classbtn c3" onclick="label(3)">3　裸地</button><button class="classbtn c4" onclick="label(4)">4　建成区</button>
<button class="classbtn cmix" onclick="label(-2,'MIXED')">混合像元（没有类别超过50%）</button>
<button class="secondary" onclick="uncertain()">影像不清，暂时无法判断</button><div class="nav"><button onclick="move(-1)">← 上一个</button><button onclick="move(1)">下一个 →</button></div>
<button class="secondary" id="auditBtn" onclick="goReview()">复核高风险旧标注</button>
<p class="muted">快捷键：0–4 标注，←/→ 切换。判读依据是 GEE 生成的 Sentinel-2 2020 年无云中位数合成影像；可在地图右上角切换当前卫星影像辅助判断。</p>
</aside>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
let points=[],idx=0,currentMarker,currentBox,map,mode='normal';
const colors=['#2563eb','#15803d','#ca8a04','#a16207','#dc2626'];
async function init(){const s=await (await fetch('/api/state')).json();points=s.points;
 map=L.map('map',{zoomControl:true}).setView([24.95,121.2],11);L.control.scale({metric:true,imperial:false}).addTo(map);
 const gee=L.tileLayer('/tiles/gee/{z}/{x}/{y}',{maxZoom:18,attribution:'Google Earth Engine / Sentinel-2 2020'});
 const esri=L.tileLayer('/tiles/esri/{z}/{x}/{y}',{maxZoom:20,attribution:'Esri World Imagery'}).addTo(map);
 L.control.layers({'当前高分影像（默认）':esri,'Sentinel-2 2020（时间参考）':gee}).addTo(map);
 const firstTodo=points.findIndex(p=>p.review_status==='TODO');idx=firstTodo<0?0:firstTodo;show();}
function updateAuditButton(){const n=points.filter(p=>p.audit_review_required).length;document.getElementById('auditBtn').textContent=`复核高风险旧标注（${n}）`}
function goReview(){const found=points.findIndex(p=>p.audit_review_required);if(found<0){alert('高风险旧标注已全部复核');return}mode='review';idx=found;show()}
function pixelBounds(p){const dLat=15/111320;const dLon=15/(111320*Math.cos(p.latitude*Math.PI/180));return [[p.latitude-dLat,p.longitude-dLon],[p.latitude+dLat,p.longitude+dLon]]}
function show(){const p=points[idx];map.setView([p.latitude,p.longitude],16);if(currentMarker)map.removeLayer(currentMarker);if(currentBox)map.removeLayer(currentBox);
 const assigned=p.review_status==='DONE'?colors[p.reference_class]:(p.review_status==='MIXED'?'#a855f7':'#f9fafb');
 currentBox=L.rectangle(pixelBounds(p),{color:assigned,weight:4,fillColor:assigned,fillOpacity:.12}).addTo(map);
 currentMarker=L.circleMarker([p.latitude,p.longitude],{radius:3,color:'#111827',weight:2,fillColor:'#fff',fillOpacity:1}).addTo(map);
 currentBox.bindTooltip('30 m × 30 m 判读范围',{permanent:true,direction:'top'}).openTooltip();
 document.getElementById('point').textContent=`${idx+1} / ${points.length}`;document.getElementById('coords').textContent=`点位 ${p.candidate_id}`;
 const done=points.filter(x=>x.review_status!=='TODO').length;document.getElementById('bar').style.width=(done/points.length*100)+'%';
 const current=p.review_status==='DONE'?`；当前已标：${['水体','植被','农地','裸地','建成区'][p.reference_class]}`:(p.review_status==='MIXED'?'；当前已标：混合像元':'');
 const audit=p.audit_review_required?'；此点需要方框复核':'';
 document.getElementById('status').textContent=`已检查 ${done}，待检查 ${points.length-done}${current}${audit}`;updateAuditButton();}
async function label(c,status='DONE'){const p=points[idx];const res=await fetch('/api/label',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:p.candidate_id,reference_class:c,review_status:status})});if(!res.ok){alert('保存失败，请重试');return}p.reference_class=c;p.review_status=status;p.audit_review_required=false;advance()}
async function uncertain(){await label(-1,'UNCERTAIN')}
function advance(){if(mode==='review'){let next=idx;for(let n=0;n<points.length;n++){next=(next+1)%points.length;if(points[next].audit_review_required){idx=next;show();return}}mode='normal'}move(1,true)}
function move(step,preferTodo=false){let next=idx;for(let n=0;n<points.length;n++){next=(next+step+points.length)%points.length;if(!preferTodo||points[next].review_status==='TODO')break}idx=next;show()}
document.addEventListener('keydown',e=>{if('01234'.includes(e.key))label(Number(e.key));else if(e.key==='ArrowLeft')move(-1);else if(e.key==='ArrowRight')move(1)});init();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    gee_tiles = ""

    def send_json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            with LOCK:
                self.send_json({"points": public_rows(), "gee_tiles": self.gee_tiles})
        elif path.startswith("/tiles/"):
            try:
                _, _, source, z, x, y = path.split("/")
                if source == "esri":
                    remote = (
                        "https://server.arcgisonline.com/ArcGIS/rest/services/"
                        f"World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    )
                elif source == "gee":
                    remote = (
                        self.gee_tiles.replace("{z}", z).replace("{x}", x).replace("{y}", y)
                    )
                else:
                    raise ValueError("Unknown tile source")
                request = urllib.request.Request(remote, headers={"User-Agent": "TaoyuanValidation/1.0"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read()
                    content_type = response.headers.get("Content-Type", "image/png")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as error:
                self.send_error(502, str(error))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/label":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length))
            reference_class = int(payload["reference_class"])
            if reference_class not in {-2, -1, 0, 1, 2, 3, 4}:
                raise ValueError("Invalid class")
            with LOCK:
                valid_ids = {item["candidate_id"] for item in read_rows()}
                if payload["candidate_id"] not in valid_ids:
                    raise StopIteration
                labels = read_labels()
                labels[payload["candidate_id"]] = {
                    "reference_class": reference_class,
                    "review_status": str(payload["review_status"]),
                    "box_reviewed": True,
                }
                write_labels(labels)
            self.send_json({"saved": True})
        except (KeyError, ValueError, StopIteration, json.JSONDecodeError) as error:
            self.send_json({"saved": False, "error": str(error)}, 400)

    def log_message(self, format: str, *args: object) -> None:
        return


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        return


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    imagery = sentinel_2020(roi)
    Handler.gee_tiles = imagery.select(["B4", "B3", "B2"]).getMapId(
        {"min": 0.02, "max": 0.3, "gamma": 1.15}
    )["tile_fetcher"].url_format
    server = QuietThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    url = "http://127.0.0.1:8765"
    print(f"Validation map ready: {url}", flush=True)
    print("Keep this window running while labeling. Press Ctrl+C to stop.", flush=True)
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
