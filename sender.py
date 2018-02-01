#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time       : 2018/1/24 17:22
# @Author     : 周星星 Siman Chou
# @Site       : https://github.com/simanchou
# @File       : sender.py
# @Description: 

from receiver import getToken, getConf, sendMessage, contentSplit, translateToCN, generateWeChatString
from receiver import AlertMQ, pruneAlerts
import json
import time
from collections import OrderedDict
import sys

cfg = getConf()
mq = AlertMQ(cfg.get("mq", "user"),
             cfg.get("mq", "password"),
             cfg.get("mq", "host"),
             cfg.get("mq", "port"),
             cfg.get("mq", "heartbeat_interval"))
channel = mq.channel

def callback(ch, method, properties, body):

    token = getToken()

    receiveData = json.loads(body.decode("utf-8"), object_pairs_hook=OrderedDict)
    myAlerts = pruneAlerts(receiveData["alerts"])
    for status, alerts in myAlerts.items():
        for alert in alerts:
            for severity, alertList in alert.items():
                if "noseverity" in severity:
                    severity = "ALL"
                if len(alertList) > 0:
                    subject = "[{}-数量:{}]".format(status, len(alertList))
                    subject = translateToCN(subject, "lang-cn")
                    alertContents = translateToCN(generateWeChatString(alertList), "lang-cn")
                    if sys.getsizeof(alertContents) < 1000:
                        content = alertContents
                        sendMessage(token, subject, content, severity)
                        #print("send to wechat successful")
                    else:
                        contentList = contentSplit(alertContents)
                        for content in contentList:
                            sendMessage(token, subject, content.strip("\n\n"), severity)
                            time.sleep(1)
                            subject = "[接上一条...]"
                        #print("send to wechat successful")
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(
    callback,
    queue='alert_wechat',
)

channel.start_consuming()
