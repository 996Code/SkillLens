# Sprint 20 验收记录：交付加固（块 J，M4 启动）

日期：2026-09-25。分支 sprint20-hardening。

## 验收结果

| # | 功能点 | 结果 | 证据 |
|---|---|---|---|
| J4 PII 规则配置化 | ✅ | `PII_PATTERNS` env（server 动态构造 SENSITIVE_KEY_RE + 插件 buildSensitiveRe 工厂）；自定义正则命中脱敏测试；.env.docker.example 示例 |
| J5 性能收尾 | ✅ | 100KB reqBody diff 性能基准（100 次 <1s，回退全文路径实测）；镜像瘦身评估：chromium --with-deps 主导，多阶段构建收益有限——记录为已知取舍 |
| J2 安装向导 | ✅ | deploy/README 重写为向导式：前置检查表 + 7 步骤（每步预期输出）+ 6 行故障排查表 |
| J3 备份恢复演练 | ✅ | **完整实测通过**（2026-09-27 Windows Docker）：容器 healthy → 造标记数据 → volume 备份（tgz 含 skilllens.db）→ compose down + 删卷 → tgz 恢复 → up → health ok + **标记会话 j3-drill-marker 完整回来**。发现并记录 Windows Git Bash 坑：MSYS 路径转换需 `MSYS_NO_PATHCONV=1`（已写入部署向导） |
| — | 三套测试 | ✅ | server **279**（275→279）/ extension **31**（28→31）/ web 34 |

## J3 演练步骤（构建完成后执行）

```bash
# 备份
docker run --rm -v skilllens_skilllens-data:/data -v $PWD:/backup alpine tar czf /backup/skilllens-data.tgz /data
# 恢复
docker compose down && docker volume rm skilllens_skilllens-data
docker volume create skilllens_skilllens-data
docker run --rm -v skilllens_skilllens-data:/data -v $PWD:/backup alpine sh -c "cd / && tar xzf /backup/skilllens-data.tgz"
docker compose up -d && curl health + skills 数据核对
```
