# 图标与转换依赖来源

| 来源 | 授权 | 固定来源记录 |
| --- | --- | --- |
| Tabler | MIT | curated.json 中逐项记录提交及路径 |
| Lucide | ISC | curated.json 中逐项记录提交及路径 |
| Health Icons | CC0-1.0 | curated.json 中逐项记录提交及路径 |
| Bioicons 精选 | CC0-1.0 | 仅取 cc-0 目录，逐项保留原作者 |
| Phosphor | MIT | expanded-phosphor.json，固定上游提交 |
| Fluent System Icons | MIT | expanded-fluent.json，Microsoft 原始 SVG |
| Material Symbols | Apache-2.0 | expanded-material.json，Google 素材经固定 Iconify 数据版本分发 |
| Iconoir | MIT | expanded-iconoir.json，固定上游提交 |
| Bootstrap Icons | MIT | expanded-bootstrap.json，固定上游提交 |
| Servier Medical Art | CC BY 3.0 | expanded-servier.json，仅取 Bioicons 的 cc-by-3.0/Servier SVG 版本 |
| Reactome | CC BY 4.0 | expanded-reactome.json，官方归档哈希及逐项详情地址 |
| svgelements 1.9.6 | MIT | toolbox_manager/vendor/icons 内保留 wheel 授权文件 |
| resvg-py 0.2.6 | MIT | toolbox_manager/vendor/icons 内保留 wheel 授权文件 |

上游完整授权文本位于本目录 licenses。图标源文件原样保存，转换版本单独生成。

新增七库使用常用样式和可转换子集，不代表完整上游库。每项保留作者、来源和版本。Servier 的当前官网授权不替换旧版 SVG 的 CC BY 3.0 标记；使用该批素材时署名 Servier Medical Art 并附带来源。Reactome 署名 CSHL、OICR 和 EBI。项目副本附带 ATTRIBUTION.txt，交付时需汇总实际使用素材的署名与修改说明。各机构商标相关权利不由素材许可证额外授予。

VTracer 用于可选描摹，Shapely 用于复合轮廓方向处理；随包依赖保留各自授权文件。安装时不自动从网络获取图标或模型。

源码来源

- https://github.com/tabler/tabler-icons
- https://github.com/lucide-icons/lucide
- https://github.com/resolvetosavelives/healthicons
- https://github.com/duerrsimon/bioicons
- https://github.com/meerk40t/svgelements
- https://github.com/baseplate-admin/resvg-py
- https://github.com/visioncortex/vtracer
- https://github.com/shapely/shapely
