# 搜狗词库爬取下载转换RIME词库工具

## 使用方式
修改download_sogou.py 文件中main函数中的参数，然后运行（全部类目下的官方推荐推荐词库，合并去重后127w，文件大小43M 左右）

![](https://h.dqy.me:1077/pub/b/2024/05/24/202405241315044.webp)
![](https://h.dqy.me:1077/pub/b/2024/05/24/202405241320225.webp)

## 注意事项
1. 环境要求：Python 3 
2. 下载方式支持两种： 方式一指定词库id和名称，方式二 指定词库类目id和名称，两者选其一或者同时使用
2. 转换使用scel2text 可能会出现部分词库无法转换，脚本会自动跳过，并且转换方法可以独立使用，在/out/scel已经下载文件后，可以单独调用download_sogou.py 中的convert_scel_to_rime_dict()方法直接转换。
3. 转换完成后，会在out/dict 目录下生成合并转换后的RIME词库文件 sogou_dict_{datetime}.dict.yaml
4. 将生成的词库文件配置到Rime的配置中,添加后重新部署输入法即可。详细挂载自定义词库文件方法，[参考](https://www.jianshu.com/p/e24f190ac280)
![](https://h.dqy.me:1077/pub/b/2024/05/24/202405241325914.webp)

