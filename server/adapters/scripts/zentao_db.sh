#!/bin/sh
# 禅道容器内 DB 探针辅助脚本（AF2）：从应用配置抽 root 密码并执行 SQL。
# 用法（经 docker exec 注入 /opt/skilllens/ 后调用）：sh zentao_db.sh "<SQL>"
# 密码只存在于容器进程内存，不落任何清单/日志（安全红线）。
PW=$(grep "password" /apps/zentao/config/my.php | head -1 | grep -oP "= '\K[^']+")
exec mysql -uroot -p"$PW" -N -e "$1"
