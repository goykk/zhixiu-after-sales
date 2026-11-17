# 智修 V1.2 演示手册库

本目录存放演示与种子数据使用的手册 Markdown 文件，由 `scripts/seed_demo.py` 读取、登记并索引。

## 目录约定

```
data/manuals/<brand-slug>/<model-slug>/<NN>-<topic>.md
```

- 每个设备目录固定 4 份手册（安装与安全、故障码、风扇与风道排查、维护清洁），共 5 个设备 20 份。
- 文件首行 `<!-- page: 1 -->` 用于切页，`#` 标题用于切节；`core/rag/chunking.py` 依此生成切片。
- 手册版本以文件名无关的分页元数据写入数据库，版本号由 `scripts/seed_demo.py` 的 `MANUAL_SPECS` 指定。

## 与检索的关系

索引后切片元数据包含 `brand/model/hardware_version/firmware_version/version/page/section`，
检索时按设备型号与版本过滤后再做向量召回与重排，引用必须携带手册版本与页码。

## 新增手册

1. 在对应设备目录下新增 `.md` 文件，保持 `<!-- page: N -->` 与 `#` 结构。
2. 在 `scripts/seed_demo.py` 的 `MANUAL_SPECS` 中登记 `path/title/version`。
3. 重新运行 `python scripts/seed_demo.py`（幂等，已存在的同型号同标题手册会更新正文并重建索引）。