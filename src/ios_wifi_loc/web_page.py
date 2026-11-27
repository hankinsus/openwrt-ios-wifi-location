from __future__ import annotations

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="__CSRF__">
<title>定位控制</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: sans-serif; margin: 0; }
  main { max-width: 36rem; margin: 0 auto; padding: 1rem; }
  h1 { font-size: 1.4rem; }
  section, form { border: 1px solid #8884; border-radius: 8px; padding: 0.8rem; margin: 0.8rem 0; }
  button, input, select { font: inherit; }
  button, input[type="text"], input[type="password"], input[type="number"], select { width: 100%; box-sizing: border-box; margin: 0.3rem 0; padding: 0.6rem; }
  button { cursor: pointer; }
  .row { display: flex; gap: 0.5rem; }
  .muted { color: #666; font-size: 0.92rem; }
  .bad { color: #a33; }
  label { display: block; margin-top: 0.4rem; }
  ul { padding-left: 1.1rem; }
</style>
</head>
<body>
<main>
  <h1>iPhone 定位控制</h1>
  <p class="muted">同一局域网里的开发者定位。手机上的真实坐标这里无法回读。</p>
  <form id="login">
    <p>口令写在本机文件里，页面不显示口令。路径见安装说明。</p>
    <label>口令 <input id="password" type="password" autocomplete="current-password"></label>
    <button type="submit">进入</button>
    <p id="login-error" class="bad"></p>
  </form>
  <div id="app" hidden>
    <section>
      <h2>状态</h2>
      <p id="command">控制命令：正在读取</p>
      <p id="session">会话进程：正在读取</p>
      <p id="phone">手机定位：未能确认</p>
      <p id="summary" class="muted"></p>
    </section>
    <section>
      <h2>设备</h2>
      <button id="discover" type="button">重新发现</button>
      <div id="devices"></div>
      <label>传输
        <select id="transport">
          <option value="usbmux">usbmux 网络</option>
          <option value="mobdev2">mobdev2</option>
          <option value="remotepairing">remotepairing</option>
        </select>
      </label>
      <label>标识 <input id="udid" type="text" autocomplete="off"></label>
      <label>主机（mobdev2 可选） <input id="host" type="text" autocomplete="off"></label>
      <button id="choose" type="button">选择这台设备</button>
    </section>
    <section>
      <h2>坐标</h2>
      <label>纬度 <input id="lat" type="text" inputmode="decimal"></label>
      <label>经度 <input id="lon" type="text" inputmode="decimal"></label>
      <label>命令族
        <select id="profile">
          <option value="ios17">iOS 17 及以上</option>
          <option value="pre17">iOS 17 以下</option>
          <option value="auto">先读取系统版本</option>
        </select>
      </label>
      <label>收藏名称 <input id="fav-name" type="text"></label>
      <button id="save-fav" type="button">保存为收藏</button>
      <ul id="favs"></ul>
      <label><input id="confirm" type="checkbox"> 我确认向已选择的手机发送上面的坐标</label>
      <button id="start" type="button">启动定位</button>
      <button id="clear" type="button">请求恢复真实定位</button>
      <button id="check" type="button">只检查连接</button>
    </section>
    <section>
      <h2>首次配对</h2>
      <pre id="guide" class="muted"></pre>
    </section>
    <button id="logout" type="button">退出</button>
    <p id="action-error" class="bad"></p>
  </div>
</main>
<script>
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
async function api(path, options) {
  const response = await fetch(path, Object.assign({
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}
  }, options || {}));
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(body.summary || "请求失败");
  return body;
}
function paint(data) {
  $("command").textContent = "控制命令：" + (data.command_accepted ? "上游已接受最近一次命令" : "尚未接受，或上次没有成功");
  $("session").textContent = "会话进程：" + (data.session_alive ? "仍在本机运行" : "没有在运行");
  $("phone").textContent = "手机定位：未能确认。进程还在不能代表手机坐标。";
  $("summary").textContent = data.summary || "";
  const box = $("devices");
  box.replaceChildren();
  (data.devices || []).forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.connection + " " + item.udid;
    button.onclick = () => { $("udid").value = item.udid; $("transport").value = item.connection === "wifi" ? "usbmux" : "mobdev2"; };
    box.appendChild(button);
  });
  const list = $("favs");
  list.replaceChildren();
  (data.favorites || []).forEach((item) => {
    const li = document.createElement("li");
    const use = document.createElement("button");
    use.type = "button";
    use.textContent = item.name + " " + item.latitude + ", " + item.longitude;
    use.onclick = () => { $("lat").value = item.latitude; $("lon").value = item.longitude; };
    li.appendChild(use);
    list.appendChild(li);
  });
  if (data.selected) $("udid").value = data.selected.udid || "";
}
async function refresh() {
  paint(await api("/api/status"));
}
$("login").onsubmit = async (event) => {
  event.preventDefault();
  $("login-error").textContent = "";
  try {
    await api("/api/login", {method: "POST", body: JSON.stringify({password: $("password").value})});
    $("password").value = "";
    $("login").hidden = true;
    $("app").hidden = false;
    $("guide").textContent = (await api("/api/guide")).text;
    await refresh();
  } catch (error) { $("login-error").textContent = error.message; }
};
$("discover").onclick = async () => { $("action-error").textContent = ""; paint(await api("/api/discover", {method: "POST", body: "{}"})); };
$("choose").onclick = async () => {
  $("action-error").textContent = "";
  try {
    paint(await api("/api/select", {method: "POST", body: JSON.stringify({udid: $("udid").value, transport: $("transport").value, host: $("host").value})}));
  } catch (error) { $("action-error").textContent = error.message; }
};
$("save-fav").onclick = async () => {
  try {
    paint(await api("/api/favorites", {method: "POST", body: JSON.stringify({name: $("fav-name").value, latitude: $("lat").value, longitude: $("lon").value})}));
  } catch (error) { $("action-error").textContent = error.message; }
};
$("start").onclick = async () => {
  $("action-error").textContent = "";
  if (!$("confirm").checked) { $("action-error").textContent = "先勾选确认，才会发送坐标。"; return; }
  try {
    paint(await api("/api/location/start", {method: "POST", body: JSON.stringify({latitude: $("lat").value, longitude: $("lon").value, profile: $("profile").value, confirm: true})}));
  } catch (error) { $("action-error").textContent = error.message; }
};
$("clear").onclick = async () => {
  try { paint(await api("/api/location/clear", {method: "POST", body: JSON.stringify({profile: $("profile").value, confirm: true})})); }
  catch (error) { $("action-error").textContent = error.message; }
};
$("check").onclick = async () => {
  try { paint(await api("/api/connection/check", {method: "POST", body: "{}"})); }
  catch (error) { $("action-error").textContent = error.message; }
};
$("logout").onclick = async () => { await api("/api/logout", {method: "POST", body: "{}"}); location.reload(); };
api("/api/status").then((data) => { $("login").hidden = true; $("app").hidden = false; paint(data); api("/api/guide").then((guide) => { $("guide").textContent = guide.text; }); }).catch(() => {});
setInterval(() => { if (!$("app").hidden) refresh().catch(() => {}); }, 4000);
</script>
</body>
</html>
"""


def render_page(csrf: str) -> str:
    return PAGE.replace("__CSRF__", csrf)
