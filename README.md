# 搜狗细胞词库 → Rime 词库工具

把一个或多个搜狗 `.scel` 细胞词库转换成可直接挂载到鼠鬚管 / 小狼毫 / 仓输入法的 Rime 词库。

- `download_sogou.py`：按词库 ID 或类目批量下载 `.scel`
- `scel2txt.py`：解析 `.scel` 并转换成 Rime dict（v2）

## 为什么要重写转换器（v2）

旧版把 100+ 个细胞词库合并成一个 100 多万行、43MB 的 `sogou_dict.dict.yaml`，看起来"很丰富"，实际用起来几乎没有价值：

1. **没有权重**：输出只有 `词<Tab>拼音`，而 dict 头写的是 `sort: by_weight`。没有权重的词条权重为 0，在候选窗口（默认只显示 5～10 个）里永远排最后，等于**白占 Rime table 空间**（约 32 字节/行，100 万行 ≈ 40MB）。
2. **`.scel` 的扩展字段不是词频**：解析后 10 字节扩展区的前 2 字节取值 0–65535，和词频/顺序无关（样本里 `可以`=13072，而 `阿坝`=55660），不能拿它当权重。旧版直接丢掉了整段扩展信息，也无法排序。
3. **不校验拼音**：词库里混进 `accept → a c c e p t`、`格ICU → ge i c u` 这类"英文拆字母"条目。Rime 会把单个字母当成音节塞进音节表，**污染简拼**——典型症状是输入 `ky` 出不了「可以」，只剩英文候选 kylie/Kyoto。
4. **只做整行去重**：既不按 `(词, 拼音)` 去重，也不和 rime-ice 等已有词库比对。重复行在 Rime table 里**不会自动合并**（实测同一份词库导入两次，table 从 17.7MB 涨到 25.6MB）。
5. **一个巨型文件**：无法按类目启用/关闭，也没法分别调权重。

v2 的处理方式：

| 能力 | 说明 |
|---|---|
| 权重 | `--weight-mode rank`（默认，按搜狗同音组顺序递减 1–50） / `jieba`（用 jieba 词频，`1+20*log10(freq)` 映射到 1–99） / `fixed` / `none` |
| 音节校验 | 内置 428 个音节（含 `lv/lve/lue/nv/nve/nue/jv` 等 ü 变体、`m/n/ng/hm/er/r`），可用 `--syllables-file` 再补 |
| 去重 | 按 `(词, 拼音)`；支持 `--exclude` 传入已有 Rime 词库，跳过重复 |
| 拆分 | `--split-by-category` 每个 `.scel` 输出一个 dict，并生成 `import_tables` 汇总文件 |
| 裁剪 | `--max-len 4`（推荐）、`--min-len`、`--min-weight`、`--keep-latin` |
| 报告 | 每个词库丢弃原因统计 + 总行数 + 预估 table 体积，可 `--report-json` |

## 安装

```bash
python3 -m pip install -r requirements.txt   # 只有下载脚本需要 beautifulsoup4
```

## 使用

### 1. 下载 .scel

编辑 `download_sogou.py` 末尾的 `download_dict({...})` / `download_dict_by_cates([...], True)`，然后：

```bash
python3 download_sogou.py
# 输出 ./out/scel/*.scel
```

### 2. 转换（推荐配置）

```bash
python3 scel2txt.py \
  --scel-dir ./out/scel \
  --out-dir ~/Library/Rime/packs \
  --name sogou \
  --split-by-category \
  --max-len 4 \
  --ascii-names \
  --weight-mode rank \
  --import-prefix packs \
  --exclude ~/Library/Rime/cn_dicts/base.dict.yaml \
            ~/Library/Rime/cn_dicts/ext.dict.yaml \
            ~/Library/Rime/user_custom_dicts/sogou_qihao_240515.dict.yaml
```

输出：

```
packs/
  sogou-11640.dict.yaml        # 每个词库一个（已带权重、已校验、已去重）
  sogou-15117.dict.yaml
  sogou.dict.yaml              # 汇总：import_tables: [packs/sogou-11640, ...]
```

然后在 Rime 的组合词库里按需导入：

```yaml
# rime_ice.pro.dict.yaml
import_tables:
  - cn_dicts/8105
  - cn_dicts/base
  - user_custom_dicts/sogou_qihao_240515
  - packs/sogou-11640
  - packs/sogou-15117
```

不用的包删掉对应 import 行再部署即可，不会进入 build（也就不会占 table）。

### 3. 用 jieba 词频当权重

```bash
curl -L https://raw.githubusercontent.com/fxsjy/jieba/master/jieba/dict.txt -o jieba_dict.txt
python3 scel2txt.py ... --weight-mode jieba --weight-map jieba_dict.txt
```

### 4. 兼容旧用法

```bash
python3 scel2txt.py ./scel ./dict sogou_all.dict.yaml
```

仍会生成单个 `sogou_all.dict.yaml`（不拆分、不限长度），但建议配合 `--max-len 4` 等参数使用。

## 体积参考（真实样本）

搜狗标准词库（`id=11640`，392,777 行）转换后：

| 策略 | 输出行数 | 与 rime-ice 现有词库去重后 | 预估 table |
|---|---|---|---|
| `--max-len 4` | 169,383 | 54,908 | **1.8MB** |
| `--max-len 5` | 318,590 | 197,626 | 6.5MB |
| 不限制长度 | 392,777 | 265,848 | 8.5MB |

结论：**5 字以上的长术语占了一半行数，但词频覆盖极低**（jieba 只覆盖 27.6% 的搜狗词，且 ≤4 字覆盖率远高于长词）。按类目拆包、限制长度、去重，才能做到"词多、体积小、还能真的出候选"。

## 注意

- Rime table 约 **32 字节/行**，体积由行数决定，和源文件 MB 数无关。
- 权重生效范围是**同一个编码下的候选排序**；建议包权重 ≤50，避免压过 base（rime-ice 的 base 权重可到千万级，ext 统一为 100）。
- 非法音节条目不是"多一个候选"的问题，而是会破坏简拼切分，务必让校验保持开启。
- 本工具的定位是"生成可裁剪的词库包"，不是"把所有搜狗词库堆进去"。
