"""QQ bot stack component."""



import json
import os
import sys
import urllib.request





for _k in ("no_proxy", "NO_PROXY"):
    _c = os.environ.get(_k, "").strip()
    os.environ[_k] = f"{_c},127.0.0.1,localhost,::1," if _c else "127.0.0.1,localhost,::1,"

URL = "http://127.0.0.1:8090/api/status"

try:
    with urllib.request.urlopen(URL, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
except Exception as e:  
    print(f"   [!!] 取不到控制台状态：{e}")
    sys.exit(1)

for s in data.get("services", []):
    mark = "[OK]" if s.get("running") else "[--]"
    pid = s.get("pid")
    extra = f"  pid={pid}" if pid else ""
    print(f"   {mark} {s.get('label', s.get('key')):<16} 端口 {s.get('port')}{extra}")

tip = (data.get("tip") or "").strip()
if tip:
    print(f"   提示：{tip}")
if not data.get("napcat_logged_in"):
    print("   QQ 还没登录：点控制台「NapCat」页签，用手机 QQ 扫码登录机器人账号。")

err = data.get("netstat_error")
if err:
    print(f"   [警告] 端口探测异常（状态可能不准）：{err}")

running = sum(1 for s in data.get("services", []) if s.get("running"))
total = len(data.get("services", []))
print(f"   —— 共 {running}/{total} 个服务在运行 ——")
