"""恢复 /forecast/ 反向代理配置（把停用页换回 proxy）"""
import re

conf = "/etc/nginx/conf.d/znote.conf"
frag = "/var/www/stock-forecast/deploy/nginx-forecast.conf"
text = open(conf, encoding="utf-8").read()

for pat in [
    r"location\s*=\s*/forecast\s*\{[^}]*\}\s*",
    r"location\s*\^~\s*/forecast/\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*",
    r"location\s*=\s*/forecast/healthz\s*\{[^}]*\}\s*",
]:
    text = re.sub(pat, "", text)

block = open(frag, encoding="utf-8").read()
idx = block.find("location")
frag_locs = block[idx:] if idx >= 0 else block

pos = text.rfind("}")
text = text[:pos] + "\n" + frag_locs + "\n" + text[pos:]
open(conf, "w", encoding="utf-8").write(text)
print("nginx conf restored")
