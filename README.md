# Alertmanager_webhook_wechat

基于Alertmanager的web_hook机制，增加微信告警。

使用方法：

1. 安装

```
pip install -r requirements.txt
```

2. 配置

```
copy prom_alert_wechat.conf.sample prom_alert_wechat.conf
```
编辑prom_alert_wechat.conf文件，填入正确的内容。

3. 运行
```
python3 ./prometheus_alert_webhook.py

```
或者

```
python3 ./prometheus_alert_webhook.py --conf yourpath/prom_webhook.conf
```

运行时若不指定配置文件路径，默认会在脚本所有目录查找配置文件，若找不到配置文件会在脚本所在目录下自动生成prom_webhook.conf文件，请先填写完整配置项再次启动。

正常启动后，可通过浏览器访问http://yourip:port/path测试web服务，正常情况下会看到如下信息：
> Current your action is 'GET', it's not allow method. Only 'POST' action is allow.


修改Alertmanager的web_hook配置，使其支持本程序，应该像下面的样子：

```
receivers:
- name: 'yourname'
  webhook_configs:
    - url: http://本程序所在主机IP:端口/alert_to_wechat
```

如果有触发了告警，本程序会在终端上打印出如下信息：
> - Receive notification from Alertmanager at Fri Nov 24 15:55:10 2017
> - Send notification to wechat successful at Fri Nov 24 15:55:10 2017


