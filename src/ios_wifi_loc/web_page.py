from __future__ import annotations

from ios_wifi_loc.windows_pair import WINDOWS_PAIR_STEP1_PS, WINDOWS_PAIR_STEP2_PS

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
html { -webkit-text-size-adjust:100%; }
body { font-family:-apple-system,system-ui,sans-serif; background:var(--bg); color:var(--text); overflow-x:hidden; }
#login-card { max-width:720px; width:100%; margin:0 auto; padding:16px; }
#app { width:100%; max-width:none; margin:0; padding:0 0 36px; }
.map-shell { width:100%; max-width:100%; margin:0; padding:0; display:block; }
.map-wrap { width:100%; max-width:100%; margin:0; border-radius:0; overflow:visible; position:relative; }
#map { height:420px; width:100%; min-height:380px; background:#d8d8dc; }
.panel { padding:16px; max-width:720px; width:100%; margin:0 auto 8px auto; }
.card { background:#fff; border-radius:12px; padding:16px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,.08); overflow:hidden; }
.card h3 { font-size:15px; font-weight:600; margin-bottom:10px; }
.coords { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:14px; color:#333; padding:8px 12px; background:var(--bg); border-radius:8px; word-break:break-all; }
.row { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
.btn { flex:1; min-width:0; padding:12px 16px; border:none; border-radius:10px; font-size:14px; font-weight:500; cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; justify-content:center; text-align:center; color:#fff; }
.btn:disabled { opacity:.6; cursor:default; }
.btn-primary { background:var(--blue); }
.btn-secondary { background:#e5e5ea; color:#333; }
.btn-danger { background:var(--red); }
.btn.success { background:var(--green); }
.btn-sm { flex:none; min-width:auto; padding:6px 12px; font-size:12px; border-radius:8px; }
.section-title { font-size:14px; font-weight:600; color:var(--text); margin:16px 0 8px 0; }
.input-row { display:flex; gap:8px; margin-top:10px; min-width:0; }
.input-row input, .field { flex:1; min-width:0; padding:10px 12px; border:1px solid #d1d1d6; border-radius:8px; font-size:14px; outline:none; width:100%; }
label { display:block; font-size:13px; color:#3a3a3c; margin-top:8px; }
.status { font-size:12px; color:var(--gray); margin-top:8px; text-align:center; }
.notice { font-size:12px; color:var(--gray); text-align:center; line-height:1.5; margin-top:8px; }
.toast { position:fixed; top:60px; left:50%; transform:translateX(-50%); background:rgba(0,0,0,.8); color:#fff; padding:10px 20px; border-radius:20px; font-size:14px; opacity:0; transition:opacity .3s; pointer-events:none; z-index:9999; max-width:90%; }
.toast.show { opacity:1; }
.layer-switch { position:absolute; top:10px; left:8px; right:8px; width:auto; max-width:none; box-sizing:border-box; z-index:1000; display:flex; gap:4px; background:rgba(255,255,255,.92); border-radius:8px; padding:4px; box-shadow:0 2px 8px rgba(0,0,0,.15); flex-wrap:wrap; justify-content:flex-end; align-content:flex-start; min-width:0; overflow-x:auto; overflow-y:hidden; -webkit-overflow-scrolling:touch; }
.layer-btn { border:none; background:transparent; padding:6px 10px; border-radius:6px; font-size:12px; cursor:pointer; color:#333; font-weight:500; flex:0 0 auto; min-width:0; white-space:nowrap; }
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
.fav-del { flex:none; width:28px; height:28px; border:1px solid #e5e5ea; border-radius:50%; background:#f2f2f7; color:#dc2626; font-size:16px; font-weight:700; cursor:pointer; line-height:1; box-shadow:0 1px 2px rgba(0,0,0,.08); display:inline-flex; align-items:center; justify-content:center; padding:0; }
.fav-del:hover { background:#ececef; color:#b91c1c; border-color:#d1d1d6; }
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
.pair-cmds { background:var(--bg); border-radius:8px; padding:10px 12px; font-size:12px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre-wrap; overflow-wrap:anywhere; word-break:break-word; margin-top:8px; color:#333; max-width:100%; }
details { margin-top:8px; }
details summary { cursor:pointer; color:#3a3a3c; font-size:13px; }
.pair-manual { margin-top:14px; }
.pair-manual summary { font-weight:600; font-size:14px; color:var(--text); padding:4px 0; }
.modal-overlay { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,.4); z-index:10000; display:none; align-items:center; justify-content:center; padding:20px; }
.modal-overlay.show { display:flex; }
.modal { background:#fff; border-radius:16px; padding:20px; width:100%; max-width:340px; }
.modal h3 { font-size:17px; font-weight:600; margin-bottom:16px; text-align:center; }
.modal input { width:100%; padding:12px; border:1px solid #d1d1d6; border-radius:10px; font-size:15px; outline:none; margin-bottom:12px; }
.footer-card { text-align:center; padding:4px 16px 8px; background:transparent; border-radius:0; box-shadow:none; margin:28px auto 0 auto; max-width:720px; }
.footer-brand { font-weight:600; font-size:15px; color:var(--text); margin-bottom:0; }
.footer-version { font-size:12px; color:var(--gray); margin-bottom:8px; font-family:ui-monospace,Menlo,monospace; font-weight:700; }
.bad { color:var(--red); font-size:13px; margin-top:8px; }
#action-error { margin:8px 0 0 0; }
#action-error:empty { display:none; margin:0; height:0; padding:0; }
#logout-wrap { margin-top:8px; }
#logout-wrap[hidden] { display:none; margin:0; }
#map-fallback { display:none; padding:24px 16px; text-align:center; color:var(--gray); font-size:13px; }
.btn, .presets button, .layer-btn, .copy-btn, .fav-del {
  -webkit-tap-highlight-color: transparent;
  transition: transform .08s ease, opacity .12s ease, box-shadow .12s ease, background .15s ease, filter .12s ease;
  box-shadow: 0 1px 2px rgba(0,0,0,.08);
}
.btn:active:not(:disabled), .presets button:active, .layer-btn:active, .copy-btn:active, .fav-del:active {
  transform: scale(0.97);
  opacity: .88;
  box-shadow: 0 0 0 0 rgba(0,0,0,0);
  filter: brightness(0.96);
}
.btn.busy { opacity:.9; }
.spinner { display:inline-block; width:12px; height:12px; border:2px solid currentColor; border-right-color:transparent; border-radius:50%; animation:spin .6s linear infinite; margin-right:6px; vertical-align:-2px; }
@keyframes spin { to { transform: rotate(360deg); } }
.toast.toast-ok { background:rgba(52,199,89,.95); color:#fff; }
.toast.toast-bad { background:rgba(255,59,48,.95); color:#fff; }
.device-bar-wrap { padding-bottom:8px; margin-bottom:0; }
.device-select { font-size:16px; padding:12px 14px; margin-top:0; font-weight:500; background:#fff; }
.device-status { margin-top:8px; font-size:13px; line-height:1.5; min-height:1.5em; }
.device-status .badge { margin-right:6px; }
.pair-steps { display:flex; flex-direction:column; gap:10px; margin:10px 0; }
.pair-step { background:var(--bg); border-radius:10px; padding:12px; }
.pair-step-h { display:flex; align-items:flex-start; gap:8px; font-size:13px; line-height:1.55; }
.step-no { flex:none; width:22px; height:22px; border-radius:50%; background:var(--blue); color:#fff; font-size:12px; font-weight:700; display:inline-flex; align-items:center; justify-content:center; margin-top:1px; }
.pair-step .pair-cmds { margin-top:8px; user-select:all; }
.copy-btn { flex:none; min-width:auto; margin-left:auto; }

.device-info { margin-top:10px; background:#e8f1ff; border:1px solid var(--blue); border-radius:10px; padding:10px 12px; display:flex; flex-direction:column; align-items:stretch; gap:6px; min-width:0; }
.device-info-head { display:flex; justify-content:space-between; align-items:center; gap:8px; min-width:0; }
.device-info-title { flex:1; min-width:0; font-size:15px; font-weight:600; line-height:1.35; overflow-wrap:anywhere; word-break:break-word; }
.device-info-meta { font-size:11px; color:#3a3a3c; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; word-break:break-all; }
.device-info .device-status { margin-top:0; min-height:0; width:100%; }
.device-info .device-status .badge { margin-right:0; display:inline-block; white-space:normal; overflow-wrap:anywhere; word-break:break-word; max-width:100%; line-height:1.35; }
.badge-pick { background:var(--blue); color:#fff; flex-shrink:0; }
.badge-connected { background:#0b7a32; color:#fff; flex-shrink:0; }
.badge-disconnected { background:#fff3cd; color:#8a6d00; flex-shrink:0; }
@media (max-width:420px) {
  .device-info-head { align-items:center; }
}
@media (max-width:1024px) {
  #map { height:36vh; min-height:280px; max-height:400px; }
}
@media (max-width:600px) {
  #login-card { max-width:100%; padding:12px; }
  #app { padding:0 0 32px; }
  .panel { padding:12px; }
  #map { height:38vh; min-height:220px; max-height:340px; }
  .btn { min-height:44px; }
  .btn-sm { min-height:36px; }
  .device-select { width:100%; }
  .layer-switch { left:8px; right:8px; max-width:none; }
  .row .btn, .shortcut-install .btn { flex:1 1 calc(50% - 8px); }
}
.pair-group { background:var(--bg); border-radius:10px; padding:12px; margin-bottom:8px; }
.pair-group-head { font-size:14px; font-weight:600; margin-bottom:8px; }
.pair-file { display:flex; align-items:center; gap:8px; padding:6px 0; font-size:12px; }
.pair-file + .pair-file { border-top:1px solid #e5e5ea; }
.pair-file-name { flex:1; min-width:0; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; word-break:break-all; }
.pair-file .badge { flex:none; }
.shortcut-install { margin:0 0 10px 0; }
.map-shell, .map-wrap { position:relative; }
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
  <div class="map-shell">
  <div class="map-wrap">
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
  </div>
  <div class="panel device-bar-wrap">
    <div class="card" style="margin-bottom:0">
      <div class="fav-header">
        <h3 style="margin-bottom:0">选择设备</h3>
        <button class="btn btn-sm btn-secondary" id="discover" type="button">重新扫描</button>
      </div>
      <select id="device-select" class="field device-select" aria-label="选择设备"></select>
      <div id="device-info" class="device-info" hidden>
        <div class="device-info-head">
          <div class="device-info-title" id="device-info-title"></div>
          <span class="badge badge-disconnected" id="device-info-picked" hidden>未连接</span>
        </div>
        <div class="device-info-meta" id="device-info-udid"></div>
        <div id="device-status" class="device-status"></div>
      </div>
      <details id="manual-device">
        <summary>高级 / 手动添加</summary>
        <p class="notice" style="text-align:left;margin:8px 0 0 0">传输类型、主机和标识仅在设备未被自动发现时需要手动填写。</p>
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
  </div>
  <div class="panel">
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
        <h3>我的收藏</h3>
        <button class="btn btn-sm btn-secondary" id="clear-favs" type="button">清空全部</button>
      </div>
      <div id="favs" class="fav-list"></div>
    </div>

    <div class="card">
      <h3>搜索地点</h3>
      <div class="input-row">
        <input id="searchInput" placeholder="输入地名（如：东京车站）或坐标（如：35.6812, 139.7671）" aria-label="搜索地点或坐标">
        <button class="btn btn-secondary" id="search" type="button" style="flex:none;min-width:56px">搜索</button>
      </div>
    </div>

    <div class="card">
      <h3>粘贴地图链接</h3>
      <div class="input-row">
        <input id="urlInput" placeholder="Apple / Google / 高德地图链接，或经纬度">
        <button class="btn btn-secondary" id="parse-url" type="button" style="flex:none;min-width:56px">解析</button>
      </div>
    </div>
    <div class="card">
      <h3>iOS 快捷指令 &amp; 地图分享</h3>
      <p class="notice" style="text-align:left;margin:0 0 10px 0">在 iPhone 上安装下面两个快捷指令后，可用「分享」把高德 / 苹果 / Google / 百度地图链接直接发给本机定位，或一键恢复真实定位。</p>
      <div class="row shortcut-install" style="margin-top:0">
        <a class="btn btn-primary" href="https://www.icloud.com/shortcuts/cf3227b48a8f484283069a087727f861" target="_blank" rel="noopener noreferrer">一键安装：地图分享定位</a>
        <a class="btn btn-primary" href="https://www.icloud.com/shortcuts/395385a36be94384a85480d7459d1fa1" target="_blank" rel="noopener noreferrer">一键安装：恢复真实定位</a>
      </div>
      <p class="notice" style="text-align:left;margin:10px 0 0 0">安装后如路由器 IP 不是默认地址，在快捷指令里改成当前路由器地址即可。</p>
    </div>

    <div class="card">
      <h3>配对管理（一键导入 .plist）</h3>
      <p class="notice" id="pair-status" style="text-align:left">正在读取配对状态…</p>
      <div id="pair-files"></div>
      <div class="row" style="margin-top:12px">
        <a class="btn btn-primary" id="download-windows-pair" href="/api/tools/windows-pair.bat">下载 Windows 一键配对工具 (.bat)</a>
      </div>
      <p class="notice" style="text-align:left;margin:8px 0 0 0">双击运行即可自动检测/安装 Python、开启开发者模式、配对开启 Wi-Fi，并按当前网页地址自动上传 2 个 <code>.plist</code> 文件。</p>
      <p class="notice" id="pair-auth-note" style="text-align:left;margin:8px 0 0 0">若服务开了口令，下载工具后请先设置环境变量 <code>IOS_WIFI_LOC_TOKEN</code> 为状态目录 <code>web.secret</code> 中的口令，再运行脚本。</p>
      <details class="pair-manual">
        <summary>展开手动配置与手动上传 (.plist)</summary>
        <div class="pair-steps">
          <div class="pair-step">
            <div class="pair-step-h">
              <span class="step-no">1</span>
              <span>安装 Apple Devices / iTunes，手机暂时关闭密码。用 PowerShell 装工具并开启开发者模式：</span>
              <button type="button" class="btn btn-sm btn-secondary copy-btn" data-copy-target="pair-cmd-1">复制</button>
            </div>
            <pre class="pair-cmds" id="pair-cmd-1">__PAIR_CMD_1__</pre>
          </div>
          <div class="pair-step">
            <div class="pair-step-h">
              <span class="step-no">2</span>
              <span>配对并开启 Wi-Fi 连接：</span>
              <button type="button" class="btn btn-sm btn-secondary copy-btn" data-copy-target="pair-cmd-2">复制</button>
            </div>
            <pre class="pair-cmds" id="pair-cmd-2">__PAIR_CMD_2__</pre>
          </div>
          <div class="pair-step">
            <div class="pair-step-h">
              <span class="step-no">3</span>
              <span>上传 <code>C:\ProgramData\Apple\Lockdown\</code> 里的 &lt;UDID&gt;.plist 和 SystemConfiguration.plist：</span>
            </div>
            <p class="notice" style="text-align:left;margin:8px 0 0 0">上传后会保存到 <code>/etc/ios-wifi-loc/lockdown</code>。macOS 路径是 /var/db/lockdown/。只需配对一次，之后可在同一局域网无线使用。</p>
          </div>
        </div>
        <div class="drop" id="drop">将 &lt;UDID&gt;.plist 和 SystemConfiguration.plist 拖到这里，或点击「选择 .plist 文件」</div>
        <input id="plist-files" type="file" accept=".plist,application/x-plist,application/xml" multiple hidden>
        <div class="row">
          <button class="btn btn-secondary" id="import-plist" type="button">选择 .plist 文件</button>
        </div>
      </details>
    </div>

    <div class="footer-card">
      <div class="footer-brand">OpenWrt 无线虚拟定位 · v0.4.7</div>
    </div>
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

function toast(msg, ms, kind) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (kind === "ok" ? " toast-ok" : kind === "bad" ? " toast-bad" : "");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { t.className = "toast"; }, ms || 2500);
}
async function withBusy(btn, busyLabel, work, doneLabel) {
  if (!btn) return work();
  const original = btn.dataset.label || btn.textContent;
  const originalClass = btn.dataset.cls || btn.className;
  btn.dataset.label = original;
  btn.dataset.cls = originalClass;
  btn.disabled = true;
  btn.classList.add("busy");
  btn.innerHTML = '<span class="spinner"></span>' + busyLabel;
  try {
    const result = await work();
    if (doneLabel) {
      btn.classList.remove("busy");
      if (btn.className.indexOf("btn-danger") < 0) btn.classList.add("success");
      btn.textContent = doneLabel;
      setTimeout(() => { btn.textContent = original; btn.className = originalClass; btn.disabled = false; }, 2200);
    } else {
      btn.textContent = original;
      btn.className = originalClass;
      btn.disabled = false;
    }
    return result;
  } catch (error) {
    btn.textContent = original;
    btn.className = originalClass;
    btn.disabled = false;
    throw error;
  }
}
function isGenericDeviceName(name) {
  const text = String(name || "").trim();
  return !text || ["iphone","ipad","ipod","ipod touch","apple"].indexOf(text.toLowerCase()) >= 0;
}
function deviceName(item) {
  const names = (lastPayload.device_names || {});
  const cached = (item && item.udid && names[item.udid]) || {};
  const selected = (lastPayload.selected && item && lastPayload.selected.udid === item.udid) ? lastPayload.selected : {};
  const picked = [item && item.name, item && item.device_name, cached.name, selected.name].filter((value) => value && !isGenericDeviceName(value));
  if (picked.length) return picked[0];
  const fallback = (item && (item.name || item.device_name)) || cached.name || selected.name;
  return fallback || "iPhone";
}
function deviceVersion(item) {
  const names = (lastPayload.device_names || {});
  const cached = (item && item.udid && names[item.udid]) || {};
  const selected = (lastPayload.selected && item && lastPayload.selected.udid === item.udid) ? lastPayload.selected : {};
  return (item && (item.product_version || item.ios_version)) || cached.product_version || selected.product_version || "";
}
function deviceTitle(item) {
  const name = deviceName(item);
  const version = deviceVersion(item);
  return version ? (name + " (iOS " + version + ")") : name;
}
function deviceCardTitle(item) {
  const name = deviceName(item);
  const version = deviceVersion(item);
  return version ? (name + " · iOS " + version) : name;
}
function deviceStatusText(item, tunneldReady) {
  if (item.waiting_for_wifi && item.watchdog_active) return "等待 Wi-Fi / 隧道恢复后自动重连…";
  if (item.waiting_reconnect && item.watchdog_active) return "等待隧道恢复自动重连…";
  if ((item.holding || item.session_alive) && item.watchdog_active) {
    const n = item.reconnect_count || 0;
    const loc = (item.latitude != null && item.longitude != null) ? (Number(item.latitude).toFixed(2) + ", " + Number(item.longitude).toFixed(2)) : "";
    return "保持中（自动重连已开启，已重连 " + n + " 次）" + (loc ? " · " + loc : "");
  }
  if (item.holding || item.session_alive) {
    if (item.latitude != null) return "模拟中 " + Number(item.latitude).toFixed(2) + ", " + Number(item.longitude).toFixed(2);
    return "模拟中";
  }
  if (item.tunnel_ready) return "隧道就绪";
  return tunneldReady ? "等待连接" : "等待隧道";
}
function paintDeviceSelect(data) {
  const sel = $("device-select");
  if (!sel) return;
  const devices = data.devices || [];
  const selectedId = (data.selected && data.selected.udid) || "";
  const ready = !!(data.tunneld && data.tunneld.reachable);
  sel.replaceChildren();
  if (!devices.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "未发现设备，请先导入配对文件或重新扫描";
    sel.appendChild(opt);
  } else {
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "请选择一台 iPhone";
    sel.appendChild(placeholder);
    devices.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item.udid;
      opt.textContent = deviceTitle(item);
      sel.appendChild(opt);
    });
  }
  sel.value = selectedId;
  const current = devices.find((d) => d.udid === selectedId);
  const info = $("device-info");
  const box = $("device-status");
  const picked = $("device-info-picked");
  if (box) box.replaceChildren();
  if (current) {
    if (info) info.hidden = false;
    if ($("device-info-title")) $("device-info-title").textContent = deviceCardTitle(current);
    const bits = [];
    if (current.transport || current.connection) bits.push(current.transport || current.connection);
    bits.push(current.udid);
    if (current.host) bits.push(current.host);
    if ($("device-info-udid")) $("device-info-udid").textContent = bits.join(" ");
    if (picked) {
      const connected = !!(current.tunnel_connected || current.tunnel_ready);
      picked.hidden = false;
      picked.textContent = connected ? "已连接" : "未连接";
      picked.className = "badge " + (connected ? "badge-connected" : "badge-disconnected");
    }
    if (box) {
      const badge = document.createElement("span");
      const waiting = (current.waiting_reconnect || current.waiting_for_wifi) && current.watchdog_active;
      const holding = current.holding || current.session_alive || current.desired;
      badge.className = "badge " + (waiting ? "badge-wait" : (holding || current.tunnel_ready ? "badge-on" : (ready ? "badge-wait" : "badge-off")));
      const statusText = deviceStatusText(current, ready);
      badge.textContent = statusText === "隧道就绪" ? "隧道已就绪" : statusText;
      box.appendChild(badge);
    }
  } else {
    if (info) info.hidden = !devices.length;
    if ($("device-info-title")) $("device-info-title").textContent = devices.length ? "请选择一台 iPhone" : "未发现设备";
    if ($("device-info-udid")) $("device-info-udid").textContent = "";
    if (picked) picked.hidden = true;
    if (box && devices.length) box.textContent = "切换上方列表即可立即选中";
  }
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
  const ready = !!(data && data.tunneld && data.tunneld.reachable);
  paintDeviceSelect(data);
  if (data.selected && data.selected.udid) $("udid").value = data.selected.udid;
  if (data.selected && data.selected.transport) $("transport").value = data.selected.transport;
  if (data.selected && data.selected.host) $("host").value = data.selected.host;
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
  const allFiles = pairing.files || [];
  const systemFiles = allFiles.filter((item) => item.system_configuration);
  const deviceFiles = allFiles.filter((item) => !item.system_configuration);
  const groups = [];
  const grouped = {};
  deviceFiles.forEach((item) => {
    const key = item.udid || item.filename;
    if (!grouped[key]) {
      const title = item.device_name || item.display_name || "未命名设备";
      const head = item.product_version ? (title + " · iOS " + item.product_version) : title;
      grouped[key] = {head, files: []};
      groups.push(grouped[key]);
    }
    grouped[key].files.push(item);
  });
  if (!groups.length && systemFiles.length) {
    groups.push({head: "系统配对配置", files: []});
  }
  groups.forEach((group) => {
    const card = document.createElement("div");
    card.className = "pair-group";
    const head = document.createElement("div");
    head.className = "pair-group-head";
    head.textContent = group.head;
    card.appendChild(head);
    const rows = group.files.concat(systemFiles);
    rows.forEach((item) => {
      const row = document.createElement("div");
      row.className = "pair-file";
      const name = document.createElement("div");
      name.className = "pair-file-name";
      name.textContent = item.filename;
      row.appendChild(name);
      const del = document.createElement("button");
      del.className = "fav-del";
      del.type = "button";
      del.textContent = "×";
      del.setAttribute("aria-label", "删除 " + item.filename);
      del.onclick = async () => {
        try {
          paint(await api("/api/pairing/" + encodeURIComponent(item.filename), {method:"DELETE", body: "{}"}));
          toast("已删除 " + item.filename);
        } catch (error) { $("action-error").textContent = error.message; }
      };
      row.appendChild(del);
      card.appendChild(row);
    });
    files.appendChild(card);
  });
}

async function refresh() { paint(await api("/api/status")); }
async function scan() {
  $("action-error").textContent = "";
  try {
    await withBusy($("discover"), "扫描中...", async () => {
      paint(await api("/api/discover", {method:"POST", body:"{}"}));
      toast("扫描完成", 2500, "ok");
    });
  } catch (error) { $("action-error").textContent = error.message; toast(error.message, 3500, "bad"); }
}
async function chooseDevice(item) {
  $("action-error").textContent = "";
  const transport = item.transport || (item.connection === "usb" ? "usbmux" : "mobdev2");
  try {
    paint(await api("/api/select", {method:"POST", body: JSON.stringify({udid: item.udid, transport, host: item.host || "", name: deviceName(item)})}));
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
  try {
    let ok = false;
    await withBusy(btn, "设置中...", async () => {
      const data = await api("/api/set", {method:"POST", body: JSON.stringify({latitude: String(lat), longitude: String(lon), profile: profileFor(), confirm: true, replace: true})});
      paint(data);
      ok = !!(data.session_alive || data.command_accepted);
      if (ok) toast("✅ 已下发定位，请在手机地图确认", 3000, "ok");
      else toast(data.summary || "已发送", 3000);
    }, null);
    if (ok) {
      btn.classList.add("success");
      btn.textContent = "✅ 已下发定位";
      const original = "设置定位";
      setTimeout(() => { btn.textContent = original; btn.className = "btn btn-primary"; btn.disabled = false; }, 2200);
    }
  } catch (error) {
    $("action-error").textContent = error.message;
    toast(error.message, 3500, "bad");
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
function parseCoordQuery(raw) {
  const text = String(raw || "").trim();
  if (!text) return null;
  const normalized = text.replace(/[，、；;]/g, ",").replace(/[°º]/g, " ").replace(/\s+/g, " ").trim();
  const num = "([+-]?\\d+(?:\\.\\d+)?)";
  const hemiLat = "([NSns])";
  const hemiLon = "([EWew])";
  let a = null, o = null;
  let m = normalized.match(new RegExp("^" + num + "\\s*" + hemiLat + "\\s*[,\\s]+\\s*" + num + "\\s*" + hemiLon + "$"));
  if (m) {
    a = parseFloat(m[1]); if (/[Ss]/.test(m[2])) a = -Math.abs(a); if (/[Nn]/.test(m[2])) a = Math.abs(a);
    o = parseFloat(m[3]); if (/[Ww]/.test(m[4])) o = -Math.abs(o); if (/[Ee]/.test(m[4])) o = Math.abs(o);
  }
  if (a == null) {
    m = normalized.match(new RegExp("^" + hemiLat + "\\s*" + num + "\\s*[,\\s]+\\s*" + hemiLon + "\\s*" + num + "$"));
    if (m) {
      a = parseFloat(m[2]); if (/[Ss]/.test(m[1])) a = -Math.abs(a); if (/[Nn]/.test(m[1])) a = Math.abs(a);
      o = parseFloat(m[4]); if (/[Ww]/.test(m[3])) o = -Math.abs(o); if (/[Ee]/.test(m[3])) o = Math.abs(o);
    }
  }
  if (a == null) {
    m = normalized.match(new RegExp("^" + num + "\\s*[,\\s]+\\s*" + num + "$"));
    if (m) { a = parseFloat(m[1]); o = parseFloat(m[2]); }
  }
  if (a == null || o == null || !isFinite(a) || !isFinite(o)) return null;
  if (Math.abs(a) > 90 && Math.abs(o) <= 90) { const t = a; a = o; o = t; }
  if (Math.abs(a) > 90 || Math.abs(o) > 180) return null;
  return {lat: a, lon: o};
}
async function searchPlace() {
  const q = $("searchInput").value.trim();
  if (!q) return toast("请输入地名或坐标");
  const parsed = parseCoordQuery(q);
  if (parsed) {
    moveTo(parsed.lat, parsed.lon, 15);
    toast("已跳转到指定坐标", 2000, "ok");
    return;
  }
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
function copyText(text) {
  const value = String(text == null ? "" : text);
  const fallback = () => {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "readonly");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    area.style.top = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    area.setSelectionRange(0, 99999);
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(area);
    return ok;
  };
  const succeed = () => { toast("已复制", 2000, "ok"); return true; };
  const fail = () => { toast("复制失败，请手动选择文本", 2500, "bad"); return false; };
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(value).then(succeed).catch(() => fallback() ? succeed() : fail());
  }
  return Promise.resolve(fallback() ? succeed() : fail());
}
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
  try {
    await withBusy($("clear"), "恢复中...", async () => {
      paint(await api("/api/location/clear", {method:"POST", body: JSON.stringify({profile: profileFor(), confirm:true})}));
      toast("✅ 已恢复真实定位，请在手机上确认", 3000, "ok");
    }, "✅ 已恢复真实定位");
  } catch (error) { $("action-error").textContent = error.message; toast(error.message, 3500, "bad"); }
};
function savedTargetCoords() {
  const selected = lastPayload.selected || {};
  const devices = lastPayload.devices || [];
  const targets = lastPayload.desired_targets || [];
  const session = lastPayload.session || {};
  const current = devices.find((d) => d.udid === selected.udid) || session;
  const target = targets.find((t) => t.udid === selected.udid && t.enabled !== false) || {};
  const lat = (current && current.latitude != null) ? current.latitude : (target.lat != null ? target.lat : target.latitude);
  const lon = (current && current.longitude != null) ? current.longitude : (target.lon != null ? target.lon : target.longitude);
  if (lat == null || lon == null) return null;
  return {lat: Number(lat), lon: Number(lon)};
}
function goDefaultTokyo() {
  moveTo(35.6812, 139.7671, 13);
  toast("已回到默认位置（东京）", 2500, "ok");
}
$("locate").onclick = async () => {
  const saved = savedTargetCoords();
  if (saved) {
    moveTo(saved.lat, saved.lon, 16);
    toast("已回到当前保存位置", 2500, "ok");
    return;
  }
  if (window.isSecureContext && navigator.geolocation) {
    try {
      await withBusy($("locate"), "定位中...", () => new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(
          (pos) => { moveTo(pos.coords.latitude, pos.coords.longitude, 16); toast("✅ 已定位到当前位置", 2500, "ok"); resolve(); },
          () => reject(new Error("geo")),
          {enableHighAccuracy:true, timeout:10000}
        );
      }));
      return;
    } catch (error) {
      goDefaultTokyo();
      return;
    }
  }
  goDefaultTokyo();
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
(function () {
  const note = $("pair-auth-note");
  if (note) note.style.display = NO_AUTH ? "none" : "";
})();
$("drop").onclick = () => $("plist-files").click();
$("plist-files").onchange = async (e) => {
  readPlistFiles(e.target.files);
  if (pendingFiles.length) {
    try {
      await withBusy($("import-plist"), "导入中...", async () => { await importPlists(); });
    } catch (error) { toast(error.message, 3500, "bad"); }
  }
};
["dragenter","dragover"].forEach((name) => $("drop").addEventListener(name, (e) => { e.preventDefault(); $("drop").classList.add("drag"); }));
["dragleave","drop"].forEach((name) => $("drop").addEventListener(name, (e) => { e.preventDefault(); $("drop").classList.remove("drag"); }));
$("drop").addEventListener("drop", (e) => readPlistFiles(e.dataTransfer.files));
$("import-plist").onclick = () => $("plist-files").click();
$("device-select").onchange = () => {
  const udid = $("device-select").value;
  if (!udid) return;
  const item = (lastPayload.devices || []).find((d) => d.udid === udid);
  if (item) chooseDevice(item);
};
document.querySelectorAll("[data-copy-target]").forEach((btn) => {
  btn.onclick = async () => {
    const target = $(btn.getAttribute("data-copy-target"));
    const value = target ? target.textContent : "";
    await copyText(value);
  };
});
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
    return (
        PAGE.replace("__CSRF__", csrf)
        .replace("__NO_AUTH__", "true" if no_auth else "false")
        .replace("__PAIR_CMD_1__", WINDOWS_PAIR_STEP1_PS)
        .replace("__PAIR_CMD_2__", WINDOWS_PAIR_STEP2_PS)
    )
