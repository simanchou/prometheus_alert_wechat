#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time       : 2017/11/23 21:54
# @Author     : 周星星 Siman Chou
# @Site       : https://github.com/simanchou
# @File       : receiver.py
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
import logging
import pika


#log = logging.getLogger("werkzeug")
#log.setLevel(logging.ERROR)

urllib3.disable_warnings()

currentPath = os.path.split(os.path.realpath(__file__))[0]

app = Flask(__name__)
app.debug = False
app.config.update(dict(
    SECRET_KEY="no one can guess",
))


class AlertMQ():

    def __init__(self, user, password, host, port, hb_interval):
        self.MQServerURL = 'amqp://{}:{}@{}:{}/%2F?heartbeat_interval={}'.format(user,
                                                                                 password,
                                                                                 host,
                                                                                 port,
                                                                                 hb_interval)
        self.queueName = 'alert_wechat'
        self.con = pika.BlockingConnection(pika.URLParameters(self.MQServerURL))
        self.channel = self.con.channel()
        self.queue = self.channel.queue_declare(self.queueName)

    def producer(self, data):
        self.channel.basic_publish(exchange='',
                                   routing_key=self.queueName,
                                   body=data)

    def close(self):
        self.con.close()


def getConf():
    """
    读取程序的配置文件，若文件不存在，则会按变量'conf_template'定义的模板生成配置，请按配置文件项目填写正确内容。
    configFile = current_path + "/prom_alert_wechat.conf"
    """

    global currentPath

    parser = optparse.OptionParser()
    parser.add_option('--conf', help='Config file', default='prom_alert_wechat.conf')
    (options, args) = parser.parse_args()

    configFile = options.conf if options.conf else os.path.join(currentPath, "prom_alert_wechat.conf")
    if os.path.exists(configFile):
        cfg = configparser.ConfigParser()
        cfg.read(configFile, encoding="utf-8")
        conf_options = ["token_url", "send_msg_url", "corpid", "secret", "agentid"]
        for i in conf_options:
            if cfg.get("weixin", i):
                pass
            else:
                print("you must input your '{}' in  conf file '{}'".format(i, configFile))
                exit(1)
        return cfg
    else:
        print("conf file '{}' doesn't exist.".format(configFile))
        exit(1)


def getTokenFromWeixin():
    """
    向微信接口请求token
    :return: token
    """

    cfg = getConf()

    data = {
        "corpid": cfg.get("weixin", "corpid"),
        "corpsecret": cfg.get("weixin", "secret")
    }
    r = requests.get(url=cfg.get("weixin", "token_url"), params=data, verify=False)
    token = r.json()["access_token"]
    return token


def getToken(tokencachefile=os.path.join(currentPath, "weixin_token_cache.pkl")):
    """
    读取本地缓存文件'weixin_token_cache.pkl'，文件类型为pickle，缓存内容元组(获得token的时间,token内容)
    比较当前时间与缓存的时间，若没超时则使用缓存的token，如已超时则重新获取，并保存本地作为缓存数据。
    微信token设定的超时时间为7200秒，本例中以7000秒为界线。
    :param tokencachefile: weixin_token_cache.pkl
    :return: token
    """

    if os.path.exists(tokencachefile):
        with open(tokencachefile, "rb") as wtc:
            data = pickle.load(wtc)
            if int(time.time()) - data[0] < 7000:
                return data[1]
            else:
                token = getTokenFromWeixin()
                with open(tokencachefile, "wb") as wtc:
                    wt_cache_data = (int(time.time()), token)
                    pickle.dump(wt_cache_data, wtc)
                return token
    else:
        token = getTokenFromWeixin()
        with open(tokencachefile, "wb") as wtc:
            wt_cache_data = (int(time.time()), token)
            pickle.dump(wt_cache_data, wtc)
        return token


def sendMessage(token, subject, content, severity_level):
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

    cfg = getConf()

    data = {
        "touser": cfg.get("weixin", "{}".format(severity_level)),
        "toparty": cfg.get("weixin", "toparty"),
        "msgtype": "text",
        "agentid": cfg.get("weixin", "agentid"),
        "text": {
            "content": subject + '\n' + content
        },
        "safe": "0"
    }
    r = requests.post(url=cfg.get("weixin", "send_msg_url") + token, data=json.dumps(data), verify=False)
    return r.text


def pruneAlerts(alertData):
    """
    如果多条rule同时触发告警，则有可能导致各种状态的告警消息混在一起，因此需要将原始数据进行分类修整。
    按stauts['firing','resolved']及severity两个维度进行分类，并去掉['instance', 'startsAt', 'endsAt', 'generatorURL']。
    :param alertData: alertmanager传过来的原始数据。
    :return: 一个字典。{'firing': [{'severity1': []}, {'severity2': []}, {'severity3': []}],
    'resolved': [{'severity1': []}, {'severity2': []}, {'severity3': []}]}
    """
    alertStatus = []
    alertSeverity = []
    for alert in alertData:
        if "status" in alert.keys() and "severity" in alert["labels"].keys():
            alertStatus.append(alert["status"])
            alertSeverity.append(alert["labels"]["severity"])
        elif "status" in alert.keys() and "severity" not in alert["labels"].keys():
            alertStatus.append(alert["status"])
            alertSeverity.append("noseverity")

    myAlerts = {}
    for i in set(alertStatus):
        myAlerts[i] = [ {j:[]} for j in set(alertSeverity)]

    for alert in alertData:
        for i in ['instance', 'startsAt', 'endsAt', 'generatorURL']:
            if i in alert.keys():
                del alert[i]
            elif i in alert["labels"].keys():
                del alert["labels"][i]
        for status, severity in myAlerts.items():
            if status == alert["status"]:
                for j in severity:
                    if "noseverity" in j.keys():
                        j["noseverity"].append(alert)
                    elif alert["labels"]["severity"] in j.keys():
                        j[alert["labels"]["severity"]].append(alert)
    return myAlerts


def generateWeChatString(alertList):
    """
    将指定分类下的告警内容合并生成string。
    :param alertList: 修整后的指定分类下的alerts。
    :return: string。
    """
    if len(alertList) > 0:
        dictTypes = (OrderedDict,)
        weChatStrings = ""
        for i in alertList:
            l_tmp = ""
            for k, v in i.items():
                v_tmp = ""
                if type(v) in dictTypes:
                    for m, n in v.items():
                        v_tmp += "{}:{}\n".format(m, n)
                    l_tmp += "{}".format(v_tmp)
                else:
                    l_tmp += "{}:{}\n".format(k, v)
            weChatStrings += l_tmp + "\n"
        return weChatStrings
    else:
        return ""


def contentSplit(content, fragmentation_len=1000, offset_str="\n\n"):
    """
    由于企业微信消息发送接口限制单条内容长度为2048字节，因此需对告警内容进行分片，多次发送
    :param content: 告警内容
    :param fragmentation_len: 分片长度，默认值1000
    :return: 以列表形式返回所有分片
    为使分片后的消息看起来更连贯，对分片后的内容进行判断，如果不是一条完全的告警，则往前偏移，直至找到完整一条的告警为止
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


def translateToCN(str, langconf):
    cfg = getConf()
    for i in cfg.options(langconf):
        if i in str:
            str = str.replace(i, cfg.get(langconf, i))
    return str


@app.route("/alert_to_wechat", methods=["GET", "POST"])
def alert_to_wechat():
    """
    View Function.
    仅接受POST请求。接受Alertmanager发送过来的数据，分析并发送微信接口。
    """
    if request.method == "GET":
        print("Not allow method.")
        return "Current your action is 'GET', it's not allow method.\nOnly 'POST' action is allow."
    elif request.method == "POST":
        cfg = getConf()
        #print(request.get_data().decode("utf-8"))
        receiveData = request.get_data().decode("utf-8")
        mq = AlertMQ(cfg.get("mq", "user"),
                     cfg.get("mq", "password"),
                     cfg.get("mq", "host"),
                     cfg.get("mq", "port"),
                     cfg.get("mq", "heartbeat_interval"))
        mq.producer(receiveData)
        mq.close()

        return "save to mq successful."


if __name__ == "__main__":
    cfg = getConf()
    host = cfg.get("webserver", "host")
    port = int(cfg.get("webserver", "port"))
    print("Starting program at [{}]".format(time.ctime()))
    app.run(host="{}".format(host), port=port, threaded=True)
