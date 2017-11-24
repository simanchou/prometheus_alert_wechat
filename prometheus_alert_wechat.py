#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time       : 2017/11/23 21:54
# @Author     : 周星星 Siman Chou
# @Site       : https://github.com/simanchou
# @File       : ssss.py
# @Description: 接收Alertmanager基于web_hook推送的告警内容，发送至微信公众号，实现微信告警。
# alertmanager中启用webhook设置如下：
# 或参考prometheus官网https://prometheus.io/docs/alerting/configuration/#<webhook_config>
# receivers:
#   - name: 'simanchou'
#     webhook_configs:
#       - url: http://127.0.0.1:5000/alert_to_wechat

from flask import Flask, request
import requests
import json
from collections import OrderedDict
import urllib3
import pickle
import time
import os
import configparser
import sys
import optparse

current_path = os.path.split(os.path.realpath(__file__))[0]

parser = optparse.OptionParser()
parser.add_option('--conf', help='Config file',default='prom_alert_wechat.conf')
(options, args) = parser.parse_args()

conf_file = options.conf if options.conf else current_path + "/prom_alert_wechat.conf"

app = Flask(__name__)
app.debug = False
app.config.update(dict(
    SECRET_KEY="no one can guess",
))

urllib3.disable_warnings()

# 程序运行配置文件模板。
conf_template = """
# 请正确填写如下各项信息，如还没有注册企业微信将无法使用本程序
# 关于企业微信开发文档请参考http://qydev.weixin.qq.com/wiki/index.php
# 或自行搜索相关信息
[weixin]
# 获取token的url
token_url = 
# 发送消息的url
send_msg_url = 
# 企业号中的企业id。
corpid = 
# 企业号中的应用secret。
secret = 
# 企业号中的应用id。
agentid = 
# 企业号中的部门id，群发时使用。多个接收者用‘|’分隔，最多支持100个。当touser为@all时忽略本参数
toparty = 
# 企业号中的成员ID列表（消息接收者，多个接收者用‘|’分隔，最多支持1000个）。特殊情况：指定为@all，则向关注该企业应用的全部成员发送
user = 

[webserver]
# 绑定主机IP
host = 0.0.0.0
# 监听端口
port = 5000
# 用于请求的uri，配置到Alertmanager的配置文件中的web_hook选项
uri = /alert_to_wechat
"""

# 读取程序的配置文件，若文件不存在，则会按变量'conf_template'定义的模板生成配置，请按配置文件项目填写正确内容。
#conf_file = current_path + "/prom_alert_wechat.conf"
if os.path.exists(conf_file):
    cfg = configparser.ConfigParser()
    cfg.read(conf_file, encoding="utf-8")
    conf_options = ["token_url", "send_msg_url", "corpid", "secret", "agentid"]
    for i in conf_options:
        if cfg.get("weixin", i):
            pass
        else:
            print("you must input your '{}' in  conf file '{}'".format(i, conf_file))
            exit(1)
    token_url = cfg.get("weixin", "token_url")
    send_msg_url = cfg.get("weixin", "send_msg_url")
    user = cfg.get("weixin", "user")
    corpid = cfg.get("weixin", "corpid")
    secret = cfg.get("weixin", "secret")
    toparty = cfg.get("weixin", "toparty")
    agentid = cfg.get("weixin", "agentid")
    host = cfg.get("webserver", "host")
    port = cfg.get("webserver", "port")
    uri = cfg.get("webserver", "uri")
else:
    with open(conf_file, "w", encoding="utf-8") as f :
        f.writelines(conf_template)
    print("conf file '{}' doesn't exist.".format(conf_file))
    print("create conf template successful,input your info first.")
    exit(1)


def get_token_from_weixin():
    """
    向微信接口请求token
    :return: token
    """
    global token_url
    global corpid
    global secret
    data = {
        "corpid": corpid,
        "corpsecret": secret
    }
    r = requests.get(url=token_url, params=data, verify=False)
    token = r.json()["access_token"]
    return token


def get_token(tokencachefile=current_path + "/weixin_token_cache.pkl"):
    """
    读取本地缓存文件'weixin_token_cache.pkl'，文件类型为pickle，缓存内容元组(获得token的时间,token内容)
    比较当前时间与缓存的时间，若没超时则使用缓存的token，如已超时则重新获取，并保存本地作为缓存数据。
    微信token设定的超时时间为7200秒，本例中以7000秒为界线。
    :param tokencachefile: weixin_token_cache.pkl
    :return: token
    """
    global corpid
    global secret
    if os.path.exists(tokencachefile):
        with open(tokencachefile, "rb") as wtc:
            data = pickle.load(wtc)
            if int(time.time()) - data[0] < 7000:
                return data[1]
            else:
                token = get_token_from_weixin()
                with open(tokencachefile, "wb") as wtc:
                    wt_cache_data = (int(time.time()), token)
                    pickle.dump(wt_cache_data, wtc)
                return token
    else:
        token = get_token_from_weixin()
        with open(tokencachefile, "wb") as wtc:
            wt_cache_data = (int(time.time()), token)
            pickle.dump(wt_cache_data, wtc)
        return token


def send_message(token, subject, content):
    """
    :参数         是否必须   说明
    :touser       否        成员ID列表（消息接收者，多个接收者用‘|’分隔，最多支持1000个）。
    :                       特殊情况：指定为@all，则向该企业应用的全部成员发送。
    :toparty      否        部门ID列表，多个接收者用‘|’分隔，最多支持100个。当touser为@all时忽略本参数。
    :totag        否        标签ID列表，多个接收者用‘|’分隔，最多支持100个。当touser为@all时忽略本参数。
    :msgtype      是        消息类型，'text'为文本类型。
    :agentid      是        企业应用的id，整型。可在应用的设置页面查看。
    :content      是        消息内容，最长不超过2048个字节。
    :safe         否        表示是否是保密消息，0表示否，1表示是，默认0。
    :return:微信接口返回的消息状态。
    """
    global user
    global toparty
    global agentid
    data = {
        "touser": user,
        "toparty": toparty,
        "msgtype": "text",
        "agentid": agentid,
        "text": {
            "content": subject + '\n' + content
        },
        "safe": "0"
    }
    r = requests.post(url=send_msg_url + token, data=json.dumps(data), verify=False)
    return r.text


def content_split(content, fragmentation_len=1800, offset_str="\n\n"):
    """
    由于企业微信消息发送接口限制单条内容长度为2048字节，因此需对告警内容进行分片，多次发送
    :param content: 告警内容
    :param fragmentation_len: 分片长度，默认值1800
    :return: 以列表形式返回所有分片
    为使分片后的消息看起来更连贯，会分片后的内容进行判断，如果不是一条完全的告警，则往后偏移，直至找到完整一条的告警为止
    完整的一条告警是以\n\n分隔的
    """
    content_new = []
    while sys.getsizeof(content) > fragmentation_len:
        _tmp_content = content[:fragmentation_len]
        if _tmp_content.rindex(offset_str) != fragmentation_len - 1:
            _tmp_offset = fragmentation_len - _tmp_content.rindex(offset_str)
            _tmp_content = _tmp_content[:fragmentation_len - _tmp_offset]
            content = content[fragmentation_len - _tmp_offset:]
            content_new.append(_tmp_content)
    if content != offset_str:
        content_new.append(content)
    return content_new


@app.route("{}".format(uri), methods=["GET", "POST"])
def index():
    """
    View Function.
    仅接受POST请求。接受Alertmanager发送过来的数据，分析并发送微信接口。
    """
    if request.method == "GET":
        print("Not allow method.")
        return "Current your action is 'GET', it's not allow method.\nOnly 'POST' action is allow."
    elif request.method == "POST":
        j_data = json.loads(request.get_data().decode("utf-8"), object_pairs_hook=OrderedDict)

        # debug alert receive interval
        print("Receive notification from Alertmanager at {}".format(time.asctime()))

        token = get_token()
        alert_status = j_data["status"]
        alert_counts = len(j_data["alerts"])
        subject = "[{}][Count:{}]".format(alert_status.upper(), alert_counts)

        dict_types = (OrderedDict,)
        alert_contents = ""
        # 仅去掉无用内容，不对内容作其它修改，遍历Alertmanager传过来的数据生成字符串作为微信的发送内容。
        for i in j_data["alerts"]:
            del i["generatorURL"]
            l_tmp = ""
            for k, v in i.items():
                v_tmp = ""
                if type(v) in dict_types:
                    for m, n in v.items():
                        v_tmp += "{}:{}\n".format(m, n)
                    l_tmp += "{}".format(v_tmp)
                else:
                    l_tmp += "{}:{}\n".format(k, v)
            alert_contents += l_tmp + "\n"

        # 对告警内容字节长度进行判断，不超过1800直接发送，超过则使用content_split进行分片，然后分片发送。
        if sys.getsizeof(alert_contents) < 1800:
            content = alert_contents
            send_status = send_message(token, subject, content)
            # 当无法接收消息时，打印微信返回消息检查
            #print(send_status)
            if json.loads(send_status)["errmsg"] == "ok":
                print("Send notification to wechat successful at {}".format(time.asctime()))
            else:
                print("Send fail, check your api info.")
        else:
            content_list = content_split(alert_contents)
            for content in content_list:
                send_status = send_message(token, subject, content.strip("\n\n"))
                # 当无法接收消息时，打印微信返回消息检查
                #print(send_status)
                if json.loads(send_status)["errmsg"] == "ok":
                    print("Send notification to wechat successful at {}".format(time.asctime()))
                else:
                    print("Send fail, check your api info.")
                time.sleep(1)                           # 发得太快会被微信警告，等待1秒
                subject = "[Follow by last one...]"     # 修改后继分片的消息标题，使消息看起来更连续
        return "send notify to wechat."


if __name__ == "__main__":
    host = cfg.get("webserver", "host")
    port = int(cfg.get("webserver", "port"))
    app.run(host="{}".format(host), port=port)

