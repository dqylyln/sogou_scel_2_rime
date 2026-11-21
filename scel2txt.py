#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜狗细胞词库 (.scel) → Rime 词库转换器 v2

相比 v1 的改进：
  1. 输出第三列权重（可按同音组顺序递减 / jieba 词频 / 固定值），不再产生"权重 0 永远排最后"的巨型词库；
  2. 拼音音节校验（含 ü 的 lv/lve/lue 等变体），丢弃非法音节（这类条目会污染 Rime 音节表、破坏简拼）；
  3. 按 (词, 拼音) 去重，并支持 --exclude 与已有词库比对，避免重复行白占 table 空间；
  4. 按来源 .scel 拆分输出（每个词库一个 dict + 一个汇总 import 文件），可按需启用；
  5. 长度 / 权重 / 拉丁字符过滤，并输出统计（行数、预估 table 大小、丢弃原因）。

用法示例：
  python3 scel2txt.py --scel-dir ./out/scel --out-dir ./out/dict \\
      --split-by-category --max-len 4 --weight-mode rank \\
      --exclude ~/Library/Rime/cn_dicts/base.dict.yaml \\
                ~/Library/Rime/cn_dicts/ext.dict.yaml \\
                ~/Library/Rime/user_custom_dicts/sogou_qihao_240515.dict.yaml \\
      --import-prefix packs

  # 用 jieba 词频当权重
  python3 scel2txt.py ... --weight-mode jieba --weight-map jieba_dict.txt

  # 兼容 v1 的位置参数（不拆分、不限制长度）
  python3 scel2txt.py ./scel ./dict sogou_all.dict.yaml
"""
import argparse
import json
import math
import os
import re
import struct
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# 音节表：标准 412 音节 + 雾凇/ü 变体 + 特殊音节（由 rime-ice 的 8105 字表整理）
# ---------------------------------------------------------------------------
SYLLABLES = frozenset("""
a ai an ang ao ba bai ban bang bao bei ben beng bi bian biang biao bie bin bing bo bu
ca cai can cang cao ce cei cen ceng cha chai chan chang chao che chen cheng chi chong chou
chu chua chuai chuan chuang chui chun chuo ci cong cou cu cuan cui cun cuo
da dai dan dang dao de dei den deng di dia dian diao die ding diu dong dou du duan dui dun duo
e ei en eng er fa fan fang fei fen feng fiao fo fou fu
ga gai gan gang gao ge gei gen geng gong gou gu gua guai guan guang gui gun guo
ha hai han hang hao he hei hen heng hong hou hu hua huai huan huang hui hun huo
ji jia jian jiang jiao jie jin jing jiong jiu ju juan jue jun jv
ka kai kan kang kao ke kei ken keng kong kou ku kua kuai kuan kuang kui kun kuo
la lai lan lang lao le lei leng li lia lian liang liao lie lin ling liu lo long lou lu luan
lue lun luo lv lve
ma mai man mang mao me mei men meng mi mian miao mie min ming miu mo mou mu
na nai nan nang nao ne nei nen neng ni nian niang niao nie nin ning niu nong nou nu nuan
nue nuo nv nve
o ou pa pai pan pang pao pei pen peng pi pian piao pie pin ping po pou pu
qi qia qian qiang qiao qie qin qing qiong qiu qu quan que qun qv
ran rang rao re ren reng ri rong rou ru rua ruan rui run ruo
sa sai san sang sao se sei sen seng sha shai shan shang shao she shei shen sheng shi shou
shu shua shuai shuan shuang shui shun shuo si song sou su suan sui sun suo
ta tai tan tang tao te tei teng ti tian tiao tie ting tong tou tu tuan tui tun tuo
wa wai wan wang wei wen weng wo wu
xi xia xian xiang xiao xie xin xing xiong xiu xu xuan xue xun xv
ya yan yang yao ye yi yin ying yo yong you yu yuan yue yun yv
za zai zan zang zao ze zei zen zeng zha zhai zhan zhang zhao zhe zhei zhen zheng zhi zhong
zhou zhu zhua zhuai zhuan zhuang zhui zhun zhuo zi zong zou zu zuan zui zun zuo
m n ng hm hng r
""".split())

# 拼音里允许出现的分隔写法（儿化音等）
PINYIN_EXTRA = frozenset({"ê"})
# 不允许出现在词条里的字符（转换自词库时常见于乱码/网址）
BAD_WORD_CHARS = frozenset('<>/\\|{}[]`^~')


# ---------------------------------------------------------------------------
# .scel 解析
# ---------------------------------------------------------------------------
def _read_u16(f):
    return struct.unpack("<H", f.read(2))[0]


def _read_utf16(f, length):
    return f.read(length).decode("utf-16-le")


def _get_hz_offset(f):
    header = f.read(128)
    if len(header) < 128:
        raise ValueError("文件过短，不是有效的 scel")
    mask = header[4]
    if mask == 0x44:
        return 0x2628
    if mask == 0x45:
        return 0x26C4
    raise ValueError("不支持的 scel 类型（无法定位词组区）")


def _get_py_map(f):
    py_map = {}
    f.seek(0x1540 + 4)
    for _ in range(5000):  # 防止异常文件死循环
        idx = _read_u16(f)
        length = _read_u16(f)
        if length == 0:
            break
        py_str = _read_utf16(f, length)
        py_map.setdefault(idx, py_str)
        if py_str == "zuo":  # 搜狗全局拼音表以 zuo 结束
            break
    return py_map


def read_scel_groups(path):
    """返回 [(拼音字符串, [词, 词, ...]), ...]，保持搜狗同音组内的原始顺序。

    同音组顺序是唯一能拿到的"搜狗排序"信息，用于生成组内 rank 权重。
    """
    groups = []
    with open(path, "rb") as f:
        file_size = os.path.getsize(path)
        f.seek(0)
        hz_offset = _get_hz_offset(f)
        py_map = _get_py_map(f)
        f.seek(hz_offset)
        while f.tell() < file_size:
            try:
                word_count = _read_u16(f)
                py_count = int(_read_u16(f) / 2)
                py_tokens = []
                ok = True
                for _ in range(py_count):
                    idx = _read_u16(f)
                    token = py_map.get(idx)
                    if token is None:
                        ok = False
                        break
                    py_tokens.append(token)
                if not ok:
                    break
                pinyin = " ".join(py_tokens)
                words = []
                for _ in range(word_count):
                    word_len = _read_u16(f)
                    word = _read_utf16(f, word_len)
                    ext_len = _read_u16(f)
                    if ext_len:
                        f.read(ext_len)
                    words.append(word)
                groups.append((pinyin, words))
            except (struct.error, UnicodeDecodeError):
                break
    return groups


# ---------------------------------------------------------------------------
# 数据装载
# ---------------------------------------------------------------------------
def load_syllables(path=None):
    syllables = set(SYLLABLES)
    if path:
        for line in open(path, encoding="utf-8"):
            if line.startswith("#") or "\t" not in line:
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            for token in parts[1].split():
                syllables.add(token)
    return syllables


def load_weight_map(path):
    weights = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                weights[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return weights


def load_exclude_pairs(paths):
    pairs = set()
    for path in paths or []:
        if not os.path.exists(path):
            print("警告：--exclude 文件不存在，已跳过：%s" % path, file=sys.stderr)
            continue
        body = False
        for line in open(path, encoding="utf-8"):
            if line.strip() == "...":
                body = True
                continue
            if not body or not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                pairs.add((parts[0], normalize_pinyin(parts[1])))
    return pairs


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------
def normalize_pinyin(pinyin):
    return pinyin.strip().lower().replace("ü", "v")


def pinyin_is_valid(pinyin, syllables):
    if not pinyin:
        return False
    for token in pinyin.split():
        if token not in syllables:
            return False
    return True


def word_is_ok(word, allow_latin):
    if not word:
        return False
    if any(ch in BAD_WORD_CHARS for ch in word):
        return False
    if not allow_latin and re.search(r"[A-Za-z0-9]", word):
        return False
    return True


def compute_weight(word, rank_weight, args, weight_map):
    if args.weight_mode == "none":
        return None
    if args.weight_mode == "fixed":
        weight = args.fixed_weight
    elif args.weight_mode == "jieba" and weight_map:
        freq = weight_map.get(word)
        if freq and freq > 0:
            weight = 1 + int(round(20 * math.log10(freq)))
            weight = min(args.jieba_max_weight, weight)
        else:
            weight = rank_weight
    else:
        weight = rank_weight
    if weight is not None and args.min_weight and weight < args.min_weight:
        return None
    return weight


def sanitize_name(text):
    text = text.strip().replace(" ", "_")
    text = re.sub(r'[\\/:*?"<>|\t\r\n]', "", text)
    return text or "dict"


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def write_dict(path, name, entries, version, comment_lines=None, import_tables=None):
    lines = ["# Rime dictionary", "# encoding: utf-8", "#"]
    for line in comment_lines or []:
        lines.append("# %s" % line)
    lines += ["", "---", "name: %s" % name, 'version: "%s"' % version,
              "sort: by_weight"]
    if import_tables:
        lines.append("import_tables:")
        for table in import_tables:
            lines.append("  - %s" % table)
    lines += ["..."]
    if entries:
        lines.append("")
        for word, pinyin, weight in entries:
            if weight is None:
                lines.append("%s\t%s" % (word, pinyin))
            else:
                lines.append("%s\t%s\t%d" % (word, pinyin, weight))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 转换主流程
# ---------------------------------------------------------------------------
def convert(scel_dir, out_dir, aggregate_name="sogou", split_by_category=False,
            import_prefix="", version=None, syllables_file=None,
            weight_map_file=None, excludes=None, max_len=0, min_len=1,
            allow_latin=False, weight_mode="rank", ascii_names=False, fixed_weight=5,
            min_weight=0, max_weight=50, jieba_max_weight=99,
            aggregate=True, report_json=None, verbose=True, **kwargs):
    """转换目录下所有 .scel。

    返回统计 dict。kwargs 兼容旧调用方的未知参数。
    """
    args = argparse.Namespace(
        weight_mode=weight_mode, fixed_weight=fixed_weight, min_weight=min_weight,
        jieba_max_weight=jieba_max_weight,
    )
    version = version or datetime.now().strftime("%Y%m%d")
    syllables = load_syllables(syllables_file)
    weight_map = load_weight_map(weight_map_file) if weight_mode == "jieba" and weight_map_file else {}
    excluded = load_exclude_pairs(excludes)

    os.makedirs(out_dir, exist_ok=True)
    scel_files = sorted(name for name in os.listdir(scel_dir) if name.endswith(".scel"))
    if not scel_files:
        print("未在 %s 找到 .scel 文件" % scel_dir, file=sys.stderr)
        return {}

    stats = {"files": [], "invalid_pinyin": 0, "bad_word": 0, "too_short": 0,
             "too_long": 0, "duplicate": 0, "low_weight": 0, "rows": 0}
    seen = set(excluded)
    categories = []
    combined_entries = []
    combined_sources = []

    for scel_name in scel_files:
        stem = sanitize_name(os.path.splitext(scel_name)[0])
        if ascii_names:
            stem = re.sub(r"[^\x00-\x7F]+", "", stem).strip("-_ ")
            stem = stem or "scel"
        groups = read_scel_groups(os.path.join(scel_dir, scel_name))
        entries = []
        file_stats = {"file": scel_name, "groups": len(groups), "rows": 0,
                      "invalid_pinyin": 0, "bad_word": 0, "too_short": 0,
                      "too_long": 0, "duplicate": 0, "low_weight": 0}
        for pinyin, words in groups:
            norm = normalize_pinyin(pinyin)
            if not pinyin_is_valid(norm, syllables):
                stats["invalid_pinyin"] += len(words)
                file_stats["invalid_pinyin"] += len(words)
                continue
            total = len(words)
            for index, word in enumerate(words):
                if len(word) < min_len:
                    stats["too_short"] += 1
                    file_stats["too_short"] += 1
                    continue
                if max_len and len(word) > max_len:
                    stats["too_long"] += 1
                    file_stats["too_long"] += 1
                    continue
                if not word_is_ok(word, allow_latin):
                    stats["bad_word"] += 1
                    file_stats["bad_word"] += 1
                    continue
                key = (word, norm)
                if key in seen:
                    stats["duplicate"] += 1
                    file_stats["duplicate"] += 1
                    continue
                rank_weight = max(1, min(max_weight, total - index))
                weight = compute_weight(word, rank_weight, args, weight_map)
                if weight is None and args.weight_mode != "none":
                    stats["low_weight"] += 1
                    file_stats["low_weight"] += 1
                    continue
                entries.append((word, norm, weight))
                seen.add(key)

        rows = len(entries)
        file_stats["rows"] = rows
        stats["rows"] += rows
        stats["files"].append(file_stats)

        if rows == 0:
            continue

        if split_by_category:
            dict_name = sanitize_name("%s-%s" % (aggregate_name, stem))
            filename = "%s.dict.yaml" % dict_name
            comment = [
                "由 sogou_scel_2_rime v2 生成（源：%s）" % scel_name,
                "权重模式：%s；最大长度：%s" % (weight_mode, max_len or "不限"),
            ]
            write_dict(os.path.join(out_dir, filename), dict_name, entries,
                       version, comment)
            categories.append((dict_name, filename, rows))
        else:
            combined_entries.extend(entries)
            combined_sources.append(scel_name)

        if verbose:
            print("%-40s %6d 行（丢弃：拼音 %d / 字符 %d / 过长 %d / 重复 %d / 低权重 %d）" % (
                scel_name, rows, file_stats["invalid_pinyin"], file_stats["bad_word"],
                file_stats["too_long"], file_stats["duplicate"], file_stats["low_weight"]))

    if split_by_category:
        if aggregate and categories:
            imports = []
            for dict_name, _filename, _rows in categories:
                imports.append("%s/%s" % (import_prefix, dict_name) if import_prefix else dict_name)
            write_dict(os.path.join(out_dir, "%s.dict.yaml" % aggregate_name),
                       aggregate_name, [], version,
                       ["由 sogou_scel_2_rime v2 生成的汇总词库（import_tables）",
                        "源：%d 个词库，共 %d 行" % (len(categories), stats["rows"])],
                       import_tables=imports)
    else:
        if combined_entries:
            write_dict(os.path.join(out_dir, "%s.dict.yaml" % aggregate_name),
                       aggregate_name, combined_entries, version,
                       ["由 sogou_scel_2_rime v2 生成（合并 %d 个词库）" % len(combined_sources),
                        "权重模式：%s；最大长度：%s" % (weight_mode, max_len or "不限")])

    stats["estimated_table_mb"] = round(stats["rows"] * 32 / 1_000_000, 2)
    if report_json:
        with open(report_json, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    if verbose:
        print("\n合计：%d 行，预估 table %.2f MB" % (stats["rows"], stats["estimated_table_mb"]))
        print("丢弃：非法拼音 %d，可疑字符 %d，过长 %d，重复 %d，低权重 %d" % (
            stats["invalid_pinyin"], stats["bad_word"], stats["too_long"],
            stats["duplicate"], stats["low_weight"]))
        print("提示：Rime table 约 32 字节/行；去掉无权重、非法音节、以及和现有词库重复的行才是真正省空间。")
    return stats


def main(scel_dir, dict_dir, dict_file_name, **kwargs):
    """兼容 download_sogou.py 的旧入口：位置参数 + 可选新参数。"""
    aggregate_name = os.path.splitext(os.path.basename(dict_file_name))[0]
    if aggregate_name.endswith(".dict"):
        aggregate_name = aggregate_name[:-5]
    return convert(scel_dir, dict_dir, aggregate_name=aggregate_name, **kwargs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="搜狗 scel → Rime 词库转换器 v2（带权重、音节校验、去重、分类拆分）")
    parser.add_argument("scel_dir", nargs="?", default="./scel", help="scel 文件目录")
    parser.add_argument("dict_dir", nargs="?", default="./dict", help="输出目录")
    parser.add_argument("dict_file_name", nargs="?", default="sogou_all.dict.yaml",
                        help="旧式单文件输出名（--split-by-category 时仅用于聚合名）")
    parser.add_argument("--scel-dir", dest="opt_scel_dir", help="同 scel_dir")
    parser.add_argument("--out-dir", dest="opt_out_dir", help="同 dict_dir")
    parser.add_argument("--name", default=None, help="词库名前缀，默认取 dict_file_name")
    parser.add_argument("--split-by-category", action="store_true",
                        help="每个 .scel 输出一个 dict，并生成汇总 import 文件")
    parser.add_argument("--import-prefix", default="",
                        help="汇总文件里 import_tables 的路径前缀（如 packs）")
    parser.add_argument("--max-len", type=int, default=0, help="最大词长（0=不限，推荐 4）")
    parser.add_argument("--min-len", type=int, default=1)
    parser.add_argument("--keep-latin", action="store_true", help="保留含拉丁字母/数字的词")
    parser.add_argument("--ascii-names", action="store_true", help="输出文件名只用 ASCII（去掉中文）")
    parser.add_argument("--weight-mode", choices=["rank", "jieba", "fixed", "none"],
                        default="rank", help="rank=同音组内递减（默认），jieba=词频，fixed=固定值")
    parser.add_argument("--weight-map", default=None, help="jieba 格式词频表（词 空格 词频 ...）")
    parser.add_argument("--fixed-weight", type=int, default=5)
    parser.add_argument("--min-weight", type=int, default=0, help="低于该权重丢弃（0=保留）")
    parser.add_argument("--max-weight", type=int, default=50, help="rank 权重上限")
    parser.add_argument("--jieba-max-weight", type=int, default=99)
    parser.add_argument("--syllables-file", default=None,
                        help="用 Rime 词库（如 cn_dicts/8105.dict.yaml）补充音节表")
    parser.add_argument("--exclude", nargs="+", default=None,
                        help="已有 Rime 词库，按 (词,拼音) 去重")
    parser.add_argument("--no-aggregate", action="store_true", help="不生成汇总 import 文件")
    parser.add_argument("--report-json", default=None, help="输出统计 JSON")
    parser.add_argument("--version", default=None, help="词库 version 字段，默认今天")
    parser.add_argument("--quiet", action="store_true")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    convert(
        scel_dir=args.opt_scel_dir or args.scel_dir,
        out_dir=args.opt_out_dir or args.dict_dir,
        aggregate_name=args.name or os.path.splitext(args.dict_file_name)[0].replace(".dict", ""),
        split_by_category=args.split_by_category,
        import_prefix=args.import_prefix,
        max_len=args.max_len, min_len=args.min_len,
        allow_latin=args.keep_latin,
        ascii_names=args.ascii_names,
        weight_mode=args.weight_mode,
        weight_map_file=args.weight_map,
        fixed_weight=args.fixed_weight,
        min_weight=args.min_weight,
        max_weight=args.max_weight,
        jieba_max_weight=args.jieba_max_weight,
        syllables_file=args.syllables_file,
        excludes=args.exclude,
        aggregate=not args.no_aggregate,
        report_json=args.report_json,
        version=args.version,
        verbose=not args.quiet,
    )
