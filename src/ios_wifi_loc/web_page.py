from __future__ import annotations

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="csrf-token" content="__CSRF__">
<title>OpenWrt 无线虚拟定位</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css">
<style>
:root { --blue:#007aff; --green:#34c759; --red:#ff3b30; --gray:#8e8e93; --bg:#f2f2f7; --text:#1c1c1e; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,system-ui,sans-serif; background:var(--bg); color:var(--text); }
#map { height:50vh; width:100%; min-height:250px; background:#d8d8dc; }
.panel { padding:16px; max-width:600px; margin:0 auto 30px auto; }
.card { background:#fff; border-radius:12px; padding:16px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
.card h3 { font-size:15px; font-weight:600; margin-bottom:10px; }
.coords { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:14px; color:#333; padding:8px 12px; background:var(--bg); border-radius:8px; word-break:break-all; }
.row { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
.btn { flex:1; min-width:100px; padding:12px 16px; border:none; border-radius:10px; font-size:14px; font-weight:500; cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; justify-content:center; text-align:center; color:#fff; }
.btn:disabled { opacity:.6; cursor:default; }
.btn-primary { background:var(--blue); }
.btn-secondary { background:#e5e5ea; color:#333; }
.btn-danger { background:var(--red); }
.btn.success { background:var(--green); }
.btn-sm { flex:none; min-width:auto; padding:6px 12px; font-size:12px; border-radius:8px; }
.section-title { font-size:14px; font-weight:600; color:var(--text); margin:16px 0 8px 0; }
.input-row { display:flex; gap:8px; margin-top:10px; }
.input-row input, .field { flex:1; padding:10px 12px; border:1px solid #d1d1d6; border-radius:8px; font-size:14px; outline:none; width:100%; }
label { display:block; font-size:13px; color:#3a3a3c; margin-top:8px; }
.status { font-size:12px; color:var(--gray); margin-top:8px; text-align:center; }
.notice { font-size:12px; color:var(--gray); text-align:center; line-height:1.5; margin-top:8px; }
.toast { position:fixed; top:60px; left:50%; transform:translateX(-50%); background:rgba(0,0,0,.8); color:#fff; padding:10px 20px; border-radius:20px; font-size:14px; opacity:0; transition:opacity .3s; pointer-events:none; z-index:9999; max-width:90%; }
.toast.show { opacity:1; }
.layer-switch { position:absolute; top:10px; right:10px; z-index:1000; display:flex; gap:4px; background:rgba(255,255,255,.92); border-radius:8px; padding:4px; box-shadow:0 2px 8px rgba(0,0,0,.15); flex-wrap:wrap; max-width:calc(100% - 20px); justify-content:flex-end; }
.layer-btn { border:none; background:transparent; padding:6px 10px; border-radius:6px; font-size:12px; cursor:pointer; color:#333; font-weight:500; }
.layer-btn.active { background:var(--blue); color:#fff; }
.active-loc { background:var(--bg); border-radius:8px; padding:10px 12px; font-size:13px; color:#333; margin-top:8px; }
.active-loc .label { font-size:11px; color:var(--gray); margin-bottom:4px; }
.active-loc .value { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px; }
.fav-list, .device-list { max-height:280px; overflow-y:auto; }
.fav-item, .device-card { display:flex; align-items:center; gap:8px; padding:10px 12px; background:var(--bg); border-radius:8px; margin-bottom:6px; cursor:pointer; border:1px solid transparent; }
.device-card.selected { border-color:var(--blue); background:#e8f1ff; }
.fav-item .fav-info, .device-card .fav-info { flex:1; min-width:0; }
.fav-item .fav-name, .device-card .fav-name { font-size:14px; font-weight:500; color:#333; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fav-item .fav-coords, .device-card .fav-coords { font-size:11px; color:#8e8e93; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; margin-top:2px; word-break:break-all; }
.fav-item .fav-del { flex:none; width:28px; height:28px; border:none; border-radius:50%; background:transparent; color:var(--red); font-size:16px; cursor:pointer; }
.fav-empty { text-align:center; color:var(--gray); font-size:13px; padding:16px 0; }
.fav-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.badge { display:inline-flex; align-items:center; font-size:11px; font-weight:600; padding:2px 8px; border-radius:999px; }
.badge-on { background:#d8f5e2; color:#0b7a32; }
.badge-off { background:#eee; color:#6e6e73; }
.badge-wait { background:#fff3cd; color:#8a6d00; }
.presets { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
.presets button { border:none; background:#e5e5ea; color:#333; border-radius:8px; padding:6px 10px; font-size:12px; cursor:pointer; }
.drop { margin-top:10px; border:1px dashed #c7c7cc; border-radius:10px; padding:16px; text-align:center; color:var(--gray); font-size:13px; background:#fafafa; }
.drop.drag { border-color:var(--blue); background:#e8f1ff; color:var(--blue); }
.pair-cmds { background:var(--bg); border-radius:8px; padding:10px 12px; font-size:12px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre-wrap; margin-top:8px; color:#333; }
details { margin-top:8px; }
details summary { cursor:pointer; color:#3a3a3c; font-size:13px; }
.modal-overlay { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,.4); z-index:10000; display:none; align-items:center; justify-content:center; padding:20px; }
.modal-overlay.show { display:flex; }
.modal { background:#fff; border-radius:16px; padding:20px; width:100%; max-width:340px; }
.modal h3 { font-size:17px; font-weight:600; margin-bottom:16px; text-align:center; }
.modal input { width:100%; padding:12px; border:1px solid #d1d1d6; border-radius:10px; font-size:15px; outline:none; margin-bottom:12px; }
.footer-card { text-align:center; padding:24px 16px; background:#fff; border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-top:16px; }
.footer-brand { font-weight:600; font-size:15px; color:var(--text); margin-bottom:4px; }
.footer-version { font-size:12px; color:var(--gray); margin-bottom:8px; font-family:ui-monospace,Menlo,monospace; font-weight:700; }
.bad { color:var(--red); font-size:13px; margin-top:8px; }
#map-fallback { display:none; padding:24px 16px; text-align:center; color:var(--gray); font-size:13px; }
</style>
</head>
<body>
<div id="login-card" class="panel" hidden>
  <div class="card">
    <h3>打开控制台</h3>
    <p class="notice">口令写在本机文件里，页面不显示口令。</p>
    <label>口令 <input id="password" type="password" autocomplete="current-password" class="field"></label>
    <div class="row"><button class="btn btn-primary" id="login-btn" type="button">进入</button></div>
    <p id="login-error" class="bad"></p>
  </div>
</div>
<div id="app" hidden>
  <div style="position:relative">
    <div id="map"></div>
    <div id="map-fallback">地图组件未能加载，仍可手动输入或粘贴坐标。</div>
    <div class="layer-switch" id="layers">
      <button class="layer-btn active" data-layer="satellite" type="button">卫星</button>
      <button class="layer-btn" data-layer="wgs84" type="button">WGS84</button>
      <button class="layer-btn" data-layer="amap" type="button">高德</button>
      <button class="layer-btn" data-layer="voyager" type="button">彩色</button>
      <button class="layer-btn" data-layer="standard" type="button">标准</button>
      <button class="layer-btn" data-layer="dark" type="button">暗色</button>
    </div>
  </div>
  <div class="panel">
    <div class="card">
      <div class="fav-header">
        <h3>设备自动发现</h3>
        <button class="btn btn-sm btn-secondary" id="discover" type="button">重新扫描</button>
      </div>
      <div id="tunneld-line" class="notice" style="text-align:left;margin:0 0 8px 0"></div>
      <div id="devices" class="device-list"></div>
      <details id="manual-device">
        <summary>手动输入标识</summary>
        <label>传输
          <select id="transport" class="field">
            <option value="mobdev2">mobdev2（无线）</option>
            <option value="usbmux">usbmux 网络</option>
            <option value="remotepairing">remotepairing</option>
          </select>
        </label>
        <label>标识 <input id="udid" class="field" type="text" autocomplete="off"></label>
        <label>主机（可选，支持 IPv6 如 fe80::1%br-lan） <input id="host" class="field" type="text" autocomplete="off"></label>
        <div class="row"><button class="btn btn-primary" id="choose" type="button">选择此设备</button></div>
      </details>
    </div>

    <div class="card">
      <h3>选择目标位置</h3>
      <div class="coords" id="coords">经度 139.767100  纬度 35.681200</div>
      <div class="presets" id="presets"></div>
      <div class="row">
        <button class="btn btn-primary" id="start" type="button">设置定位</button>
        <button class="btn btn-secondary" id="add-fav" type="button">收藏位置</button>
        <button class="btn btn-secondary" id="locate" type="button">当前位置</button>
      </div>
      <div class="row">
        <button class="btn btn-danger" id="clear" type="button">一键恢复真实定位</button>
      </div>
    </div>

    <div class="card">
      <div class="fav-header">
        <h3>收藏的位置</h3>
        <button class="btn btn-sm btn-secondary" id="clear-favs" type="button">清空全部</button>
      </div>
      <div id="favs" class="fav-list"></div>
    </div>

    <div class="card">
      <h3>当前模拟状态</h3>
      <div class="active-loc">
        <div class="label">本机命令与会话</div>
        <div class="value" id="command-line">正在读取…</div>
      </div>
      <div class="active-loc">
        <div class="label">手机定位</div>
        <div class="value" id="phone-line">未能确认。进程还在不能代表手机坐标。</div>
      </div>
      <p class="notice" id="summary" style="text-align:left"></p>
    </div>

    <div class="card">
      <h3>粘贴地图链接</h3>
      <div class="input-row">
        <input id="urlInput" placeholder="Apple / Google / 高德地图链接，或经纬度">
        <button class="btn btn-secondary" id="parse-url" type="button" style="flex:none;min-width:56px">解析</button>
      </div>
    </div>

    <div class="card">
      <h3>搜索地点</h3>
      <div class="input-row">
        <input id="searchInput" placeholder="输入地名（如: 东京车站）">
        <button class="btn btn-secondary" id="search" type="button" style="flex:none;min-width:56px">搜索</button>
      </div>
    </div>

    <div class="card">
      <h3>配对管理（一键导入 .plist）</h3>
      <p class="notice" id="pair-status" style="text-align:left">正在读取配对状态…</p>
      <div id="pair-files"></div>
      <div class="drop" id="drop">将 &lt;UDID&gt;.plist 和 SystemConfiguration.plist 拖到这里，或点击选择文件</div>
      <input id="plist-files" type="file" accept=".plist,application/x-plist,application/xml" multiple hidden>
      <div class="row"><button class="btn btn-primary" id="import-plist" type="button">导入选中的文件</button></div>
      <details>
        <summary>在电脑上生成配对文件（只需一次）</summary>
        <div class="pair-cmds" id="guide">pymobiledevice3 lockdown pair
pymobiledevice3 lockdown wifi-connections on

Windows: C:\\ProgramData\\Apple\\Lockdown\\
macOS: /var/db/lockdown/

把对应的 &lt;UDID&gt;.plist 和 SystemConfiguration.plist 导入即可，不用再通过 SCP 拷到路由器。</div>
      </details>
    </div>

    <div class="footer-card">
      <div class="footer-brand">OpenWrt 无线虚拟定位</div>
      <div class="footer-version">v0.3.0</div>
      <p class="notice">仅供受信局域网使用。请勿把 47321 端口暴露到公网。</p>
    </div>
    <div class="status" id="status">在地图上选好位置后点击「设置定位」，然后在手机地图确认</div>
    <p id="action-error" class="bad"></p>
    <p class="notice" id="logout-wrap" hidden><button class="btn btn-sm btn-secondary" id="logout" type="button">退出</button></p>
  </div>
</div>
<div class="toast" id="toast"></div>
<div class="modal-overlay" id="favModal">
  <div class="modal">
    <h3>收藏此位置</h3>
    <input id="favNameInput" placeholder="输入备注名称（如: 公司、家）" maxlength="30">
    <div style="font-size:12px;color:var(--gray);margin-bottom:12px;text-align:center" id="favModalCoords"></div>
    <div class="row">
      <button class="btn btn-secondary" id="fav-cancel" type="button">取消</button>
      <button class="btn btn-primary" id="fav-save" type="button">保存</button>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
<script>

const csrf = document.querySelector('meta[name="csrf-token"]').content;
const NO_AUTH = __NO_AUTH__;
const $ = (id) => document.getElementById(id);
const CITIES = [
  {name:"东京", lat:35.6812, lon:139.7671},
  {name:"纽约", lat:40.7128, lon:-74.0060},
  {name:"洛杉矶", lat:34.0522, lon:-118.2437},
  {name:"伦敦", lat:51.5074, lon:-0.1278},
  {name:"新加坡", lat:1.3521, lon:103.8198},
  {name:"香港", lat:22.3193, lon:114.1694},
  {name:"台北", lat:25.0330, lon:121.5654},
  {name:"首尔", lat:37.5665, lon:126.9780}
];
let lat = 35.6812, lon = 139.7671;
let map = null, marker = null, currentLayer = null, tiles = null, layerName = "satellite";
let lastPayload = {};
let pendingFiles = [];

function toast(msg, ms) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), ms || 2500);
}
function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
async function api(path, options) {
  const opts = Object.assign({
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}
  }, options || {});
  const response = await fetch(path, opts);
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(body.summary || "请求失败");
  return body;
}

const PI = Math.PI, GZ_A = 6378245.0, GZ_EE = 0.00669342162296594323;
function outOfChina(a, o) { return o < 72.004 || o > 137.8347 || a < 0.8293 || a > 55.8271; }
function transLat(x, y) {
  let r = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*Math.sqrt(Math.abs(x));
  r += (20*Math.sin(6*x*PI) + 20*Math.sin(2*x*PI)) * 2 / 3;
  r += (20*Math.sin(y*PI) + 40*Math.sin(y/3*PI)) * 2 / 3;
  r += (160*Math.sin(y/12*PI) + 320*Math.sin(y*PI/30)) * 2 / 3;
  return r;
}
function transLon(x, y) {
  let r = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*Math.sqrt(Math.abs(x));
  r += (20*Math.sin(6*x*PI) + 20*Math.sin(2*x*PI)) * 2 / 3;
  r += (20*Math.sin(x*PI) + 40*Math.sin(x/3*PI)) * 2 / 3;
  r += (150*Math.sin(x/12*PI) + 300*Math.sin(x/30*PI)) * 2 / 3;
  return r;
}
function wgsToGcj(a, o) {
  if (outOfChina(a, o)) return {lat:a, lon:o};
  let dLat = transLat(o - 105, a - 35);
  let dLon = transLon(o - 105, a - 35);
  const rad = a / 180 * PI;
  let magic = Math.sin(rad);
  magic = 1 - GZ_EE * magic * magic;
  const sqrt = Math.sqrt(magic);
  dLat = (dLat * 180) / ((GZ_A * (1 - GZ_EE)) / (magic * sqrt) * PI);
  dLon = (dLon * 180) / (GZ_A / sqrt * Math.cos(rad) * PI);
  return {lat: a + dLat, lon: o + dLon};
}
function gcjToWgs(a, o) {
  if (outOfChina(a, o)) return {lat:a, lon:o};
  let wgs = {lat:a, lon:o};
  for (let i = 0; i < 6; i++) {
    const gcj = wgsToGcj(wgs.lat, wgs.lon);
    wgs = {lat: wgs.lat + (a - gcj.lat), lon: wgs.lon + (o - gcj.lon)};
  }
  return wgs;
}
function displayLatLng() {
  if (!map || layerName !== "amap") return {lat, lon};
  const g = wgsToGcj(lat, lon);
  return {lat:g.lat, lon:g.lon};
}
function fromMapClick(mlat, mlon) {
  if (layerName === "amap") {
    const w = gcjToWgs(mlat, mlon);
    return {lat:w.lat, lon:w.lon};
  }
  return {lat:mlat, lon:mlon};
}
function fmtCoords() {
  let text = "WGS84 经度 " + lon.toFixed(6) + "  纬度 " + lat.toFixed(6);
  if (layerName === "amap") {
    const g = wgsToGcj(lat, lon);
    text += "（高德/GCJ-02 " + g.lon.toFixed(6) + ", " + g.lat.toFixed(6) + "）";
  }
  return text;
}
function setPos(newLat, newLon) {
  lat = newLat; lon = newLon;
  if (marker) marker.setLatLng([displayLatLng().lat, displayLatLng().lon]);
  $("coords").textContent = fmtCoords();
}
function moveTo(newLat, newLon, zoom) {
  setPos(newLat, newLon);
  if (map) map.setView([displayLatLng().lat, displayLatLng().lon], zoom || 15);
}

function initMap() {
  if (typeof L === "undefined") {
    $("map").style.display = "none";
    $("map-fallback").style.display = "block";
    $("layers").style.display = "none";
    return;
  }
  map = L.map("map").setView([lat, lon], 13);
  tiles = {
    satellite: L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {maxZoom:19, attribution:"ArcGIS"}),
    wgs84: L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {maxZoom:19, attribution:"ArcGIS"}),
    standard: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom:19, attribution:"OSM"}),
    dark: L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {maxZoom:19, attribution:"Carto"}),
    amap: L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}", {maxZoom:18, subdomains:"1234", attribution:"AMap"}),
    voyager: L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {maxZoom:19, attribution:"Carto"})
  };
  currentLayer = tiles.satellite;
  currentLayer.addTo(map);
  const shown = displayLatLng();
  marker = L.marker([shown.lat, shown.lon], {draggable:true}).addTo(map);
  marker.on("dragend", (e) => {
    const p = e.target.getLatLng();
    const w = fromMapClick(p.lat, p.lng);
    setPos(w.lat, w.lon);
  });
  map.on("click", (e) => {
    const w = fromMapClick(e.latlng.lat, e.latlng.lng);
    setPos(w.lat, w.lon);
  });
}
function switchLayer(name) {
  if (!tiles || !tiles[name]) return;
  map.removeLayer(currentLayer);
  layerName = name;
  currentLayer = tiles[name];
  currentLayer.addTo(map);
  document.querySelectorAll(".layer-btn").forEach((b) => b.classList.toggle("active", b.dataset.layer === name));
  setPos(lat, lon);
}

function paint(data) {
  lastPayload = data || {};
  const tunneld = data.tunneld || {};
  const ready = !!tunneld.reachable;
  $("tunneld-line").textContent = ready
    ? ("tunneld 已运行，发现 " + ((tunneld.tunnels || []).length) + " 条无线隧道")
    : "tunneld 未运行。iOS 17+ 无线定位需要它，安装后应由系统服务自动拉起。";
  const box = $("devices");
  box.replaceChildren();
  const devices = data.devices || [];
  if (!devices.length) {
    const empty = document.createElement("div");
    empty.className = "fav-empty";
    empty.textContent = "还没有发现设备。确认手机和路由器在同一局域网，并且已经导入配对文件。";
    box.appendChild(empty);
  }
  const selectedId = (data.selected && data.selected.udid) || "";
  devices.forEach((item) => {
    const card = document.createElement("div");
    card.className = "device-card" + (item.udid === selectedId ? " selected" : "");
    const info = document.createElement("div");
    info.className = "fav-info";
    const name = document.createElement("div");
    name.className = "fav-name";
    name.textContent = (item.name || "iPhone") + (item.product_version ? ("  iOS " + item.product_version) : "");
    const meta = document.createElement("div");
    meta.className = "fav-coords";
    let metaText = (item.transport || item.connection || "") + "  " + item.udid + (item.host ? ("  " + item.host) : "");
    if (item.holding || item.session_alive) {
      if (item.latitude != null && item.longitude != null) metaText += "  模拟中 " + item.latitude + ", " + item.longitude;
      else metaText += "  模拟进程运行中";
    }
    meta.textContent = metaText;
    info.appendChild(name);
    info.appendChild(meta);
    const badge = document.createElement("span");
    if (item.holding || item.session_alive) {
      badge.className = "badge badge-on";
      badge.textContent = (item.latitude != null) ? ("模拟中 " + Number(item.latitude).toFixed(4) + ", " + Number(item.longitude).toFixed(4)) : "模拟中";
    } else {
      badge.className = "badge " + (item.tunnel_ready ? "badge-on" : (ready ? "badge-wait" : "badge-off"));
      badge.textContent = item.tunnel_ready ? "隧道已就绪" : "等待连接";
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm btn-primary";
    btn.textContent = item.udid === selectedId ? "已选择" : "选择此设备";
    btn.onclick = () => chooseDevice(item);
    card.appendChild(info);
    card.appendChild(badge);
    card.appendChild(btn);
    box.appendChild(card);
  });
  if (data.selected && data.selected.udid) $("udid").value = data.selected.udid;
  if (data.selected && data.selected.transport) $("transport").value = data.selected.transport;
  if (data.selected && data.selected.host) $("host").value = data.selected.host;
  $("command-line").textContent = (data.command_accepted ? "上游已接受最近一次命令" : "尚未接受，或上次没有成功")
    + "；会话进程" + (data.session_alive ? "仍在本机运行" : "没有在运行");
  $("phone-line").textContent = "未能确认。进程还在不能代表手机坐标，请在苹果地图查看蓝点。";
  $("summary").textContent = data.summary || "";
  $("status").textContent = data.summary || "在地图上选好位置后点击「设置定位」，然后在手机地图确认";
  const list = $("favs");
  list.replaceChildren();
  const favs = data.favorites || [];
  $("clear-favs").style.display = favs.length ? "" : "none";
  if (!favs.length) {
    const empty = document.createElement("div");
    empty.className = "fav-empty";
    empty.textContent = "暂无收藏，选好位置后点击「收藏位置」";
    list.appendChild(empty);
  }
  favs.forEach((item) => {
    const row = document.createElement("div");
    row.className = "fav-item";
    row.onclick = () => { moveTo(parseFloat(item.latitude), parseFloat(item.longitude), 15); };
    const info = document.createElement("div");
    info.className = "fav-info";
    const name = document.createElement("div");
    name.className = "fav-name";
    name.textContent = item.name;
    const meta = document.createElement("div");
    meta.className = "fav-coords";
    meta.textContent = item.longitude + ", " + item.latitude;
    info.appendChild(name);
    info.appendChild(meta);
    const del = document.createElement("button");
    del.className = "fav-del";
    del.type = "button";
    del.textContent = "×";
    del.onclick = async (event) => {
      event.stopPropagation();
      try { paint(await api("/api/favorites/delete", {method:"POST", body: JSON.stringify({id: item.id})})); toast("已删除: " + item.name); }
      catch (error) { $("action-error").textContent = error.message; }
    };
    row.appendChild(info);
    row.appendChild(del);
    list.appendChild(row);
  });
  const pairing = data.pairing || {};
  $("pair-status").textContent = "已导入 " + (pairing.count || 0) + " 个配对文件"
    + (pairing.has_system_configuration ? "，含 SystemConfiguration.plist" : "（还没有 SystemConfiguration.plist）")
    + "。" + (ready ? "无线隧道服务已就绪。" : "等待 tunneld 连接。");
  const files = $("pair-files");
  files.replaceChildren();
  (pairing.files || []).forEach((item) => {
    const row = document.createElement("div");
    row.className = "fav-item";
    const info = document.createElement("div");
    info.className = "fav-info";
    const name = document.createElement("div");
    name.className = "fav-name";
    name.textContent = item.filename;
    const meta = document.createElement("div");
    meta.className = "fav-coords";
    meta.textContent = item.udid ? ("UDID " + item.udid) : (item.system_configuration ? "系统配对配置" : "");
    info.appendChild(name);
    info.appendChild(meta);
    const del = document.createElement("button");
    del.className = "fav-del";
    del.type = "button";
    del.textContent = "×";
    del.onclick = async () => {
      try {
        paint(await api("/api/pairing/" + encodeURIComponent(item.filename), {method:"DELETE", body: "{}"}));
        toast("已删除 " + item.filename);
      } catch (error) { $("action-error").textContent = error.message; }
    };
    row.appendChild(info);
    row.appendChild(del);
    files.appendChild(row);
  });
}

async function refresh() { paint(await api("/api/status")); }
async function scan() {
  $("action-error").textContent = "";
  $("discover").disabled = true;
  try { paint(await api("/api/discover", {method:"POST", body:"{}"})); toast("扫描完成"); }
  catch (error) { $("action-error").textContent = error.message; toast(error.message); }
  finally { $("discover").disabled = false; }
}
async function chooseDevice(item) {
  $("action-error").textContent = "";
  const transport = item.transport || (item.connection === "usb" ? "usbmux" : "mobdev2");
  try {
    paint(await api("/api/select", {method:"POST", body: JSON.stringify({udid: item.udid, transport, host: item.host || ""})}));
    toast("已选择 " + (item.name || item.udid));
  } catch (error) { $("action-error").textContent = error.message; toast(error.message); }
}
function profileFor() {
  const selected = lastPayload.selected || {};
  const version = selected.product_version || (lastPayload.devices || []).find((d) => d.udid === selected.udid)?.product_version;
  if (version && parseInt(version, 10) < 17) return "pre17";
  return "ios17";
}
async function setLocation(immediate) {
  $("action-error").textContent = "";
  if (!(lastPayload.selected && lastPayload.selected.udid)) { toast("请先选择设备"); return; }
  const btn = $("start");
  btn.disabled = true; btn.textContent = "设置中…";
  try {
    const data = await api("/api/location/start", {method:"POST", body: JSON.stringify({latitude: String(lat), longitude: String(lon), profile: profileFor(), confirm: true})});
    paint(data);
    if (data.session_alive || data.command_accepted) {
      btn.textContent = "✓ 已发送";
      btn.className = "btn btn-primary success";
      toast("本机模拟进程运行中，请在手机地图确认");
      setTimeout(() => { btn.textContent = "设置定位"; btn.className = "btn btn-primary"; btn.disabled = false; }, 2500);
    } else {
      btn.textContent = "设置定位"; btn.disabled = false;
      toast(data.summary || "已发送");
    }
  } catch (error) {
    btn.textContent = "设置定位"; btn.disabled = false;
    $("action-error").textContent = error.message;
    toast(error.message, 3500);
  }
}

function parseMapUrl(text) {
  let m;
  const raw = text.trim();
  if ((m = raw.match(/(?:coordinate|ll|sll)=(-?\d{1,3}\.\d+)(?:,|%2C)(-?\d{1,3}\.\d+)/i))) return {lat:parseFloat(m[1]), lon:parseFloat(m[2]), gcj:/amap|gaode|autonavi/i.test(raw)};
  if ((m = raw.match(/@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)/))) return {lat:parseFloat(m[1]), lon:parseFloat(m[2]), gcj:/amap|gaode|autonavi/i.test(raw)};
  if ((m = raw.match(/[?&]q=(-?\d{1,3}\.\d+)(?:,|%2C)(-?\d{1,3}\.\d+)/i))) return {lat:parseFloat(m[1]), lon:parseFloat(m[2]), gcj:/amap|gaode|autonavi/i.test(raw)};
  if ((m = raw.match(/[?&](?:lng|longitude)=(-?\d{1,3}\.\d+).*?[?&](?:lat|latitude)=(-?\d{1,3}\.\d+)/i))) return {lat:parseFloat(m[2]), lon:parseFloat(m[1]), gcj:/amap|gaode|autonavi/i.test(raw)};
  if ((m = raw.match(/(-?\d{1,3}\.\d+)\s*[,，\s]\s*(-?\d{1,3}\.\d+)/))) {
    const a = parseFloat(m[1]), b = parseFloat(m[2]);
    // If the first number looks like longitude (>90 abs), swap.
    if (Math.abs(a) > 90 && Math.abs(b) <= 90) return {lat:b, lon:a, gcj:/amap|gaode|autonavi/i.test(raw)};
    return {lat:a, lon:b, gcj:/amap|gaode|autonavi/i.test(raw)};
  }
  return null;
}
async function searchPlace() {
  const q = $("searchInput").value.trim();
  if (!q) return toast("请输入地名");
  toast("搜索中…");
  try {
    const r = await fetch("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + encodeURIComponent(q), {headers:{"Accept-Language":"zh-CN,zh;q=0.9,en;q=0.6"}});
    const results = await r.json();
    if (!results.length) return toast("未找到地点: " + q);
    moveTo(parseFloat(results[0].lat), parseFloat(results[0].lon), 15);
    toast((results[0].display_name || q).slice(0, 40));
  } catch (e) { toast("搜索失败（需要浏览器能访问公开地图检索）"); }
}

function readPlistFiles(fileList) {
  const files = Array.from(fileList || []).filter((f) => /\.plist$/i.test(f.name));
  if (!files.length) { toast("请选择 .plist 文件"); return; }
  pendingFiles = files;
  $("drop").textContent = "已选择 " + files.map((f) => f.name).join("、");
}
async function importPlists() {
  if (!pendingFiles.length) return toast("请先选择或拖入 .plist 文件");
  const files = [];
  for (const file of pendingFiles) {
    if (file.size > 256 * 1024) { toast(file.name + " 超过 256KB"); return; }
    const buf = await file.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    files.push({filename: file.name.split(/[/\\]/).pop(), content_base64: btoa(bin)});
  }
  try {
    paint(await api("/api/pairing/import", {method:"POST", body: JSON.stringify({files})}));
    toast("配对文件已导入");
    pendingFiles = [];
    $("drop").textContent = "将 <UDID>.plist 和 SystemConfiguration.plist 拖到这里，或点击选择文件";
  } catch (error) { $("action-error").textContent = error.message; toast(error.message, 3500); }
}

function showApp() {
  $("login-card").hidden = true;
  $("app").hidden = false;
  $("logout-wrap").hidden = NO_AUTH;
  if (!map) initMap();
  setTimeout(() => { if (map) map.invalidateSize(); }, 200);
}
async function afterLogin() {
  showApp();
  try { const guide = await api("/api/guide"); if (guide.text) $("guide").textContent = guide.text; } catch (e) {}
  try { await refresh(); } catch (e) {}
  try { await scan(); } catch (e) {}
}

CITIES.forEach((city) => {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = city.name;
  btn.onclick = async () => { moveTo(city.lat, city.lon, 14); await setLocation(true); };
  $("presets").appendChild(btn);
});
document.querySelectorAll(".layer-btn").forEach((b) => b.addEventListener("click", () => switchLayer(b.dataset.layer)));
$("discover").onclick = scan;
$("choose").onclick = async () => {
  try {
    paint(await api("/api/select", {method:"POST", body: JSON.stringify({udid:$("udid").value, transport:$("transport").value, host:$("host").value})}));
    toast("已记录选择");
  } catch (error) { $("action-error").textContent = error.message; toast(error.message); }
};
$("start").onclick = () => setLocation(false);
$("clear").onclick = async () => {
  $("action-error").textContent = "";
  try { paint(await api("/api/location/clear", {method:"POST", body: JSON.stringify({profile: profileFor(), confirm:true})})); toast("已请求恢复真实定位，请在手机上确认"); }
  catch (error) { $("action-error").textContent = error.message; toast(error.message, 3500); }
};
$("locate").onclick = () => {
  if (!navigator.geolocation) return toast("浏览器不支持定位");
  navigator.geolocation.getCurrentPosition(
    (pos) => moveTo(pos.coords.latitude, pos.coords.longitude, 16),
    (err) => toast("定位失败: " + err.message, 3000),
    {enableHighAccuracy:true, timeout:10000}
  );
};
$("add-fav").onclick = () => {
  $("favModalCoords").textContent = lon.toFixed(6) + ", " + lat.toFixed(6);
  $("favNameInput").value = "";
  $("favModal").classList.add("show");
  setTimeout(() => $("favNameInput").focus(), 100);
};
$("fav-cancel").onclick = () => $("favModal").classList.remove("show");
$("fav-save").onclick = async () => {
  const name = $("favNameInput").value.trim();
  if (!name) return toast("请输入备注名称");
  try {
    paint(await api("/api/favorites", {method:"POST", body: JSON.stringify({name, latitude:String(lat), longitude:String(lon)})}));
    $("favModal").classList.remove("show");
    toast("已收藏: " + name);
  } catch (error) { toast(error.message); }
};
$("clear-favs").onclick = async () => {
  if (!confirm("确定清空所有收藏？")) return;
  const favs = lastPayload.favorites || [];
  for (const item of favs) {
    try { await api("/api/favorites/delete", {method:"POST", body: JSON.stringify({id: item.id})}); } catch (e) {}
  }
  try { await refresh(); toast("已清空所有收藏"); } catch (e) { toast(e.message); }
};
$("parse-url").onclick = () => {
  const input = $("urlInput").value.trim();
  if (!input) return toast("请粘贴地图链接或坐标");
  const res = parseMapUrl(input);
  if (!res) return toast("无法解析坐标格式");
  let a = res.lat, o = res.lon;
  if (res.gcj) { const w = gcjToWgs(a, o); a = w.lat; o = w.lon; }
  moveTo(a, o, 15);
  toast("已解析为 WGS-84 坐标");
};
$("search").onclick = searchPlace;
$("searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") searchPlace(); });
$("urlInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("parse-url").click(); });
$("drop").onclick = () => $("plist-files").click();
$("plist-files").onchange = (e) => readPlistFiles(e.target.files);
["dragenter","dragover"].forEach((name) => $("drop").addEventListener(name, (e) => { e.preventDefault(); $("drop").classList.add("drag"); }));
["dragleave","drop"].forEach((name) => $("drop").addEventListener(name, (e) => { e.preventDefault(); $("drop").classList.remove("drag"); }));
$("drop").addEventListener("drop", (e) => readPlistFiles(e.dataTransfer.files));
$("import-plist").onclick = importPlists;
$("login-btn").onclick = async () => {
  $("login-error").textContent = "";
  try {
    await api("/api/login", {method:"POST", body: JSON.stringify({password: $("password").value})});
    $("password").value = "";
    await afterLogin();
  } catch (error) { $("login-error").textContent = error.message; }
};
$("password").addEventListener("keydown", (e) => { if (e.key === "Enter") $("login-btn").click(); });
$("logout").onclick = async () => { await api("/api/logout", {method:"POST", body:"{}"}); location.reload(); };
$("coords").textContent = fmtCoords();

if (NO_AUTH) {
  afterLogin().catch(() => { showApp(); });
} else {
  api("/api/status").then(async (data) => { await afterLogin(); paint(data); }).catch(() => { $("login-card").hidden = false; });
}
setInterval(() => { if (!$("app").hidden) refresh().catch(() => {}); }, 4000);
</script>
</body>
</html>
"""


def render_page(csrf: str, no_auth: bool = False) -> str:
    return PAGE.replace("__CSRF__", csrf).replace("__NO_AUTH__", "true" if no_auth else "false")
