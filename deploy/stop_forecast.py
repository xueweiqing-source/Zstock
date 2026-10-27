"""把 /forecast/ 相关 location 换成停用提示页"""
import re

conf = "/etc/nginx/conf.d/znote.conf"
text = open(conf, encoding="utf-8").read()

for pat in [
    r"location\s*=\s*/forecast\s*\{[^}]*\}\s*",
    r"location\s*\^~\s*/forecast/\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*",
    r"location\s*=\s*/forecast/healthz\s*\{[^}]*\}\s*",
]:
    text = re.sub(pat, "", text)

block = """
# stock-forecast 服务已停用（2026-10-19）
location = /forecast { return 301 /forecast/; }
location ^~ /forecast/ {
    default_type text/html;
    return 503 '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>服务已停用</title></head><body style="font-family:Microsoft YaHei,sans-serif;max-width:520px;margin:80px auto;color:#333"><h2>stock-forecast 服务已停用</h2><p>定时任务与 Web 服务均已关闭（2026-10-19）。</p><p>如需恢复，联系管理员执行恢复脚本即可。</p></body></html>';
}
"""

pos = text.rfind("}")
text = text[:pos] + block + "\n" + text[pos:]
open(conf, "w", encoding="utf-8").write(text)
print("nginx conf updated")
