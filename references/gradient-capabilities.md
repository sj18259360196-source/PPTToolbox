# 渐变与共享轮廓

从 1.24.0 起，先用 `graphics_inspect` 读取当前配方合同。全页计划仍写在 page_plan.notes，先确定几何、孔洞、遮挡和材料组，再分配拟合工作。

`graphics_probe_gradient` 接收已授权 project、最多九个 samples 和可选 background。每个 sample 含 style，可设 size。工具生成原生矩形小样，实际 Office 保存重开后读回属性、导出图像并采样中线颜色。Agent 必须查看图像，特别核对径向色标方向、焦点和宽高比。小样不会自动修改现有作品。

`graphics_fit_gradient` 保留单层模式。多层模式传 image、mask 和 layered_linear。mask 是排除文字、边缘、遮挡后的可见区域。layered_linear 必须提供 frame 像素尺寸、background 六位 RGB、provenance、按背面到正面排序的 components、候选 layer_counts。每层含 id、angle_deg、fill_alpha、stop_alpha。角度与透明度作为已知约束，只拟合双色标 RGB。有效透明度等于两项 alpha 相乘。工具用空间分块留出样本比较量化后的候选，并返回背景透过率。默认二十秒预算，最多六层。参数无法从扁平图片唯一还原，结果需要 Office 对照。

同轮廓材料使用配方 material_groups。把闭合 paths 的 visible 设为 false，由 material_groups 的 source 引用，layers 按背面到正面排列，每层包含稳定 id 和 style。order 只列材料组。修改几何源后用 graphics_regenerate 同步所有层，手工修改过 PPT 时先处理冲突。PPT 内各层仍是独立原生对象，直接拖一个层的节点不会自动同步其他层。

`graphics_gradient_roundtrip` 接收 project、pptx 项目内路径、pptx_sha256 和 operations。gradient.stop 使用 slide、name、index、property、expected、value，property 可为 color、position、alpha。gradient.angle 使用 slide、name、expected、value。索引从一开始，颜色是六位 RGB。工具在副本修改，拒绝旧预期、无效值、无变化和跨越相邻色标的位置。保存关闭重开后分别读回并导出页面。

`graphics_read_properties` 先筛选 targets 再读取深层属性，支持 timeout_seconds。Office 工作在独立进程与新副本中，runs/graphics-evidence 保存 request、stage、stdout、stderr 和 result。超时返回 outcome_unknown，不终止用户的 PowerPoint。先检查副本、日志、Office 锁及进程所有者；不要删除未知锁或盲目重试。取消正在运行的任务仍由宿主控制，本接口尚无独立取消令牌。

`graphics_scene_preflight` 根据场景文件所在目录检查结构、路径和证据字段，不修改项目。预检后仍需走当前受管导入与审查。

`graphics_select_versions` 接收 base 的 scene 与 sha256，以及 selections。每个选择指定历史 scene、sha256、slide、顶层组 id 和 dependencies，至少明确一个背景或合成依赖。只接受原生路径组和相同坐标框，依赖不一致时拒绝。输出内存提案及 scene_base，不自动采用；保存时保留原相对路径基准，再进行受管导入。该接口支持组的层数变化，尚不支持带图片的历史组。

案例中最终使用 132 个原生渐变对象。历史三次填充编辑验证只涉及纯色，不能当作渐变编辑证明。新增工具的实际验证记录单独保存；经验条目保留这一界限。全页相似、编辑读回和 scene 复现分别检查。
