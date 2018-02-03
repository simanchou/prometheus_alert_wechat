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
                        try:
                            sendMessage(token, subject, content, severity)
                        except:
                            print("Can't connect to Wexin, waiting for 5 seconds.")
                            time.sleep(5)
                            sendMessage(token, subject, content, severity)
                        finally:
                            print("[{}] Connect to Wexin fail.".format(time.asctime()))
                    else:
                        contentList = contentSplit(alertContents)
                        for content in contentList:
                            try:
                                sendMessage(token, subject, content.strip("\n\n"), severity)
                                time.sleep(1)
                                subject = "[接上一条...]"
                            except:
                                print("Can't connect to Wexin, waiting for 5 seconds.")
                                time.sleep(5)
                                sendMessage(token, subject, content.strip("\n\n"), severity)
                                subject = "[接上一条...]"
                            finally:
                                print("[{}] Connect to Wexin fail.".format(time.asctime()))
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(
    callback,
    queue='alert_wechat',
)

if mq.con.is_open:
    print("Connect to MQ successful,waiting for alert message.")
    channel.start_consuming()
else:
    print("MQ server is running, waiting for 10 seconds.")
    time.sleep(10)
    channel.start_consuming()
