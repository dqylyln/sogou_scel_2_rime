#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import urllib
import urllib.parse as url_parse
import urllib.request as url_request
from datetime import datetime

from bs4 import BeautifulSoup

import scel2txt as convert

'''
定义运行需要的目录路径
'''
# 脚本当前目录
base_dir = os.path.dirname(os.path.abspath(__file__))
# 输出文件总目录
output_dir = base_dir + '/out'
# 下载scel 词库文件目录
scel_dir = output_dir + '/scel'
# 转换后rime dict 目录
rime_dict_dir = output_dir + '/dict'

# 文件名不合法字符
invalid_symbols = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']

'''
指定词库id和名称集合，下载词库

@param dicts: 词库id和名称集合，格式如下：

dicts = {
    '搜狗标准词库': 11640,
    '计算机词汇大全': 15117,
}

参考词库详情连接: https://pinyin.sogou.com/dict/detail/index/11640

'''


def download_dict(dicts: dict):
    for dict in dicts:
        url = 'https://pinyin.sogou.com/d/dict/download_cell.php?id=%d&name=%s' % (
            dicts[dict], url_parse.quote(dict))
        download(url, os.path.join(scel_dir, str(dict) + '.scel'))


'''
指定词库类目ID和名称集合，下载对应类目下所有词库词库，

@param cates: 词库类目ID和名称集合，id 是必须的，名称用来打印日志区别使用，参考格式如下：

cates = [
    ["城市信息", 167],
    ["自然科学", 1],
    ["社会科学", 76],
    ["工程应用", 96],
    ["农林渔畜", 127],
    ["医学医药", 132],
    ["电子游戏", 436],
    ["艺术设计", 154],
    ["生活百科", 389],
    ["运动休闲", 367],
    ["人文科学", 31],
    ["娱乐休闲", 403]
]

参考类目详情连接: https://pinyin.sogou.com/dict/cate/index/1

@param recommend: True/False,是否只下载官方推荐词库
'''


def download_dict_by_cates(cates: list, recommend: bool):
    for cate in cates:
        current_page = 1
        total_page = __cate_page_download(cate[1], current_page, recommend)
        # 后面还有分页,继续下载
        while current_page < total_page:
            current_page += 1
            total_page = __cate_page_download(cate[1], current_page, recommend)


def __cate_page_download(cate_id: int, page_num: int, recommend: bool):
    # 查询指定类目id对应页码的html内容
    html = url_request.urlopen("https://pinyin.sogou.com/dict/cate/index/" + str(cate_id) + "/default/" + str(page_num))
    # 解析html 内容
    bs_obj = BeautifulSoup(html.read(), "html.parser")
    # 获取类目下词库名称html对象列表
    name_list = bs_obj.findAll("div", {"class": "detail_title"})
    # 获取类目下词库下载连接的html对象列表
    dict_url_list = bs_obj.findAll("div", {"class": "dict_dl_btn"})
    total_page = page_num
    # 获取当前类目下分页信息
    page_navigate_div = bs_obj.find("div", {"id": "dict_page_list"})
    page_a_elements = page_navigate_div.findAll('a')

    # 分页导航是数字+下一页的模式，所以下一页之前的数字连接即为最大分页
    if len(page_a_elements) > 1:
        last_a_tag = page_a_elements[len(page_a_elements) - 2]
        total_page = int(last_a_tag.get_text())

    # 判断该类目下是否有词库
    if len(name_list) == 0:
        print('%s类目: 无可用词库! 执行跳过 ...' % cate_id)
        return total_page

    if len(dict_url_list) == 0:
        print('%s类目: 无下载连接，不支持下载! 执行跳过 ...' % cate_id)
        return total_page

    # 下载dict_url_list 中的词库
    for name, url in zip(name_list, dict_url_list):
        name = name.a.get_text()
        # 如果开启推荐词库下载，名称不是推荐词库就跳过
        if recommend and name.find("官方推荐") == -1:
            continue
        # 网页中获取的词库名称可能有非法字符,需要替换
        for char in name:
            if char in invalid_symbols:
                name = name.replace(char, "")  # 去除windows文件命名中非法的字符
        # 下载
        download(url.a.attrs['href'], scel_dir + "/" + name + ".scel")

    return total_page


def download(url: str, file: str):
    # 确保目录存在
    if not os.path.exists(os.path.dirname(file)):
        os.makedirs(os.path.dirname(file))
    # 如果文件存在，先删除确保文件是最新的
    if os.path.exists(file):
        os.remove(file)
    # 发送请求下载词库文件
    print('下载"%s": %s ...' % (file, url))
    urllib.request.urlretrieve(url, file)


def convert_scel_to_rime_dict():
    # 获取当前日期
    current_date = datetime.now()
    # 获取两位数的年份
    two_digit_year = str(current_date.year)[-2:]
    # 创建一个新的日期对象，年份替换为两位数
    short_year_date = datetime.strptime(two_digit_year + current_date.strftime('%m%d'), '%y%m%d')
    # 输出格式化的日期
    formatted_short_year_date = short_year_date.strftime('%y%m%d')

    dict_file_name = 'sogou_dict_' + formatted_short_year_date + '.dict.yaml'
    # 开始转换
    convert.main(scel_dir, rime_dict_dir, dict_file_name)


if __name__ == "__main__":
    # 指定词库id和名称集合，下载词库
    download_dict({
        '搜狗标准词库': 11640,
        '计算机词汇大全': 15117,
    })

    # 指定词库类目和是否推荐方式下载词库
    download_dict_by_cates([
        ["城市信息", 360],
        ["自然科学", 1],
        ["社会科学", 76],
        ["工程应用", 96],
        ["农林渔畜", 127],
        ["医学医药", 132],
        ["电子游戏", 436],
        ["艺术设计", 154],
        ["生活百科", 389],
        ["运动休闲", 367],
        ["人文科学", 31],
        ["娱乐休闲", 403]
    ], True)
    # 转换scel文件为text，并且合并成rime 的dict文件
    convert_scel_to_rime_dict()
