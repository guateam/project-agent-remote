import json
import os
import random
import re
import string
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error
import smtplib
import requests
import lxml
import hashlib
import math

from bs4 import BeautifulSoup
from CF.cf import item_cf, set_similarity_vec, user_cf
from vague_search.vague_search import select_by_similarity, compute_tf
from API.identify import identify
from flask import Flask, jsonify, request, redirect
from flask_cors import CORS
from werkzeug.utils import secure_filename
from email.mime.text import MIMEText
from email.header import Header
from API.db import Database, generate_password

from API.utils import *

app = Flask(__name__)
CORS(app, supports_credentials=True)

"""
    常量区
"""
USER_GROUP = ['系统管理员', '从业者', '专家', '企业', '封禁', '待审核专家', '待审核企业']
LEVEL_EXP = [0, 100, 1000, 10000, 100000, 1000000]
ARTICLE_ALLOWED_GROUP = [0, 2, 3]

CF_PATH = "/etc/project-agent/CF/"
# CF_PATH = "../CF/"

RATE_DIR = "rate_rect/"
SIMILAR_DIR = "similar_rect/"

USER_RATE_NAME = "user_rate_rect.txt"
USER_ID_NAME = "user_id_list.txt"
USER_SIMILAR_NAME = "user_similar_rect.txt"

ARTICLE_RATE_NAME = "article_rate_rect.txt"
ARTICLE_ID_NAME = "article_id_list.txt"
ARTICLE_SIMILAR_NAME = "article_similar_rect.txt"

QUESTION_RATE_NAME = "question_rate_rect.txt"
QUESTION_ID_NAME = "question_id_list.txt"
QUESTION_SIMILAR_NAME = "question_similar_rect.txt"

PAY_DICT = [
    "付费回答",
    "专家咨询",
    "告示板需求",
    "文章付费",
    "文章收入",
    "专家咨询收入",
    "专家拒绝回答退款",
    "充值",
    "提现"
]

# @app.before_request
# def before_request():
# if request.url.startswith('http://'):
#     url = request.url.replace('http://', 'https://', 1)
#     return redirect(url, code=301)


@app.route("/")
def first_cry():
    return jsonify({"code": 1, 'msg': 'success'})


def random_char():
    """
    获取随机25个字符的字符串
    :return: 字符串
    """
    ran_str = ''.join(random.sample(string.ascii_letters + string.digits, 25))  # 获取随机25个字符
    return ran_str


def new_token():
    """
    获取一个不重复的token
    :return: token
    """
    db = Database()
    token = random_char()
    check = db.get({'token': token}, 'users')  # 检查token是否可用
    if check:
        return new_token()  # 递归调用
    return token


"""
    用户接口
"""
@app.route('/api/account/complain')
def complain():
    """
    举报某一条评论
    :return:code(-2=举报失败 -1=未知评论，0=用户不存在 1=举报成功)
    """

    # 用户token和评论的ID
    token = request.values.get('token')
    comment_id = request.values.get('id')
    reason = request.values.get('reason')
    # 1-回答评论  2-文章评论  3-问题评论  4-回答   5-话题   6-文章
    report_type = request.values.get('report_type')
    data_name = ""
    cmt_name = ""
    act_type = ""
    if report_type == 1:
        data_name = "answercomments"
        cmt_name = "acommentID"
        act_type = 5
    elif report_type == 2:
        data_name = "article_comments"
        cmt_name = "article_comment_id"
        act_type = 27
    elif report_type == 3:
        data_name = "questioncomments"
        cmt_name="qcommentID"
        act_type = 16
    elif report_type == 4:
        data_name = "answers"
        cmt_name="answerID"
        act_type = 6
    elif report_type == 5:
        data_name = "questions"
        cmt_name="questionID"
        act_type = 15
    elif report_type == 6:
        data_name = "article"
        cmt_name="articleID"
        act_type = 26
    # 初始化数据库控制类
    db = Database()
    # 查询用户是否存在
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'the user is not exist'})
    # 查询举报对象是否存在
    comment = db.get({cmt_name: comment_id}, data_name)
    if not comment:
        return jsonify({'code': -1, 'msg': 'the comment is not exist'})
    # 更新评论状态
    result = db.update({cmt_name: comment_id}, {'state': 1}, data_name)
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})
    # 记录用户行为
    db.insert({'userID': user['userID'], 'targetID': comment[cmt_name], 'targettype': act_type})
    # 插入举报记录
    db.insert({'reporter': user['userID'], 'itemID': comment[cmt_name], 'author': comment['userID'],'reason': reason, 'type':report_type}, 'report_log')

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/account/back_get_complain')
def back_get_complain():
    """
    后台获取所有举报记录
    :return:
    """
    db = Database()
    log = db.get({} ,'report_log')
    return jsonify({'code': 1, 'msg': 'success', 'data': log})

@app.route('/api/account/wx_openid')
def openid():
    appid = request.values.get('appid')
    appsecret = request.values.get('secret')
    code = request.values.get('code')

    url = "https://api.weixin.qq.com/sns/jscode2session?appid=" + appid + "&secret=" + appsecret + "&js_code=" \
          + code + "&grant_type=authorization_code"
    req = urllib.request.Request(url)
    data = urllib.request.urlopen(req).read()
    return data


@app.route('/api/account/send_check_code')
def send_check_code():
    """
    发送验证码到手机或邮箱
    :return:
    """
    account = request.values.get('account')
    aim = account
    if 'aim' in request.values.keys():
        aim = request.values.get('aim')
    check_code = ""
    user = None
    target = ""
    db = Database()
    # 验证用户手否存在
    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', account):
        user = db.get({'email': account}, 'users')
        if not user:
            return jsonify({'code': -1, 'msg': 'user not exist'})
        target = "email"
    elif re.match(r"^1[35678]\d{9}$", account):
        user = db.get({'phonenumber': account}, 'users')
        if not user:
            return jsonify({'code': -1, 'msg': 'user not exist'})
        target = "phonenumber"
    else:
        return jsonify({'code': 0, 'msg': 'error'})

    # 根据目标发送类型分情况发送短信和邮件
    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', aim):
        check_code = send_email(aim)
    elif re.match(r"^1[35678]\d{9}$", aim):
        check_code = phone_message(aim)
    else:
        return jsonify({'code': 0, 'msg': 'error'})

    db.update({target: account}, {'check_code': check_code}, 'users')

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/account/check_code')
def check_code():
    """
    检查验证码是否正确
    :return:
    """
    account = request.values.get('account')
    code = request.values.get('check_code')
    if code == '':
        return jsonify({'code': 0, 'msg': 'error'})

    db = Database()
    # 字段名
    target = ''
    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', account):
        target = 'email'
    elif re.match(r"^1[35678]\d{9}$", account):
        target = 'phonenumber'
    else:
        return jsonify({'code': 0, 'msg': 'error'})

    check_code = db.sql("select check_code from users where " + target + "='%s'" % account)

    if check_code and check_code[0]['check_code'] == code:
        db.update({target: account}, {'check_code': ''}, 'users')
        return jsonify({'code': 1, 'msg': 'success'})

    return jsonify({'code': 0, 'msg': 'error'})


@app.route('/api/account/update_password')
def update_password():
    """
    更新密码
    :return:
    """
    account = request.values.get('account')
    password = request.values.get('password')
    db = Database()
    # 字段名
    target = ''
    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', account):
        target = 'email'
    elif re.match(r"^1[35678]\d{9}$", account):
        target = 'phonenumber'
    else:
        return jsonify({'code': 0, 'msg': 'error'})

    result = db.update({target: account}, {'password': generate_password(password)}, 'users')

    if result:
        return jsonify({'code': 1, 'msg': 'success'})
    else:
        return jsonify({'code': 0, 'msg': 'error'})


@app.route('/api/account/validate')
def validate():
    """
    新账号验证
    :return:
    """
    account = request.values.get('account')
    check_code = request.values.get('check_code')
    target = ""

    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', account):
        target = "email"
    elif re.match(r"^1[35678]\d{9}$", account):
        target = "phonenumber"
    else:
        return jsonify({'code': 0, 'msg': 'error'})

    db = Database()
    user = db.get({target: account, 'check_code': check_code}, 'users')
    if not user:
        return jsonify({'code': -1, 'msg': 'check code error'})

    result = db.update({target: account}, {'validate': 1}, 'users')

    if result:
        return jsonify({'code': 1, 'msg': 'success'})

    return jsonify({'code': 0, 'msg': 'error'})


def phone_message(phone_num):
    check_code = ''
    length = 6
    dict = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
    for i in range(length):
        idx = random.randint(0, len(dict) - 1)
        check_code += dict[idx]
    host = 'http://dingxin.market.alicloudapi.com'
    path = '/dx/sendSms'
    method = 'POST'
    appcode = 'f3c635d6f4a24c1e9e4af7f0622030eb'
    querys = 'mobile=' + phone_num + '&param=code%3A' + check_code + '&tpl_id=TP19031326'
    bodys = {}
    url = host + path + '?' + querys

    rq = urllib.request.Request(url)
    rq.method = method
    rq.add_header('Authorization', 'APPCODE ' + appcode)
    response = urllib.request.urlopen(rq)
    content = response.read()
    return check_code


def send_email(receivers):
    sender = 'ZhuanPlus@163.com'
    password = "zhuanplus123"

    check_code = ''
    length = 6
    dict = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
    for i in range(length):
        idx = random.randint(0, len(dict) - 1)
        check_code += dict[idx]

    content = "<html><h3>这是一封来自专+的邮件 </h3><p>尊敬的 专+ 用户，您的验证码为<strong style = 'color:brown'>" + check_code
    content += "</strong>打死都不要将该验证码告诉他人</p><br><span> 感谢您对 专+ 的使用和支持 </span></html>"

    # 三个参数：第一个为文本内容，第二个 plain 设置文本格式，第三个 utf-8 设置编码
    message = MIMEText(content, 'html', 'utf-8')
    message['From'] = "<" + sender + ">"  # 发送者
    message['To'] = "<" + receivers + ">"  # 接收者
    # message['Cc'] = Header(receivers, 'utf-8')  # 抄送者
    # 邮件标题
    subject = '专+验证码'
    message['Subject'] = Header(subject, 'utf-8')

    smtpObj = smtplib.SMTP('smtp.163.com')
    smtpObj.login(sender, password)
    smtpObj.sendmail(sender, receivers, message.as_string())
    return check_code


@app.route('/api/account/if_register')
def if_register():
    openid = request.values.get("openid")
    if openid == '':
        return jsonify({'code': -2, 'msg': 'openid error'})
    db = Database()
    user = db.sql("select * from users where openid='%s' " % openid)
    if user:
        if user[0]['openid'] and user[0]['openid'] != '':
            token = new_token()
            db.update({'openid': openid},
                      {'token': token,
                       'last_login': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))},
                      'users')  # 更新token
            return jsonify({'code': 1, 'msg': 'the user is total exist', 'data': token})
        else:
            return jsonify({'code': -1, 'msg': 'the user is exist,but not bind weixin'})

    return jsonify({'code': 0, 'msg': 'the user is not exist'})


@app.route('/api/account/wx_register', methods=['POST'])
def wx_register():
    """
    在微信端的绑定邮箱 + 注册
    :return:
    """
    email = request.form['email']
    password = request.form['password']
    openid = ""
    nickname = ''
    gender = ""
    head = ""
    # 检查是否存在来自微信的openid参数传入
    if 'openid' in request.form.keys():
        openid = request.form['openid']
    if 'nickname' in request.form.keys():
        nickname = request.form['nickname']
    if 'gender' in request.form.keys():
        gender = request.form['gender']
    if 'head' in request.form.keys():
        head = request.form['head']

    db = Database()
    email_check = db.get({'email': email}, 'users')
    if not email_check:
        token = new_token()
        flag = db.insert({
            'email': email,
            'password': generate_password(password),
            'nickname': nickname,
            'openid': openid,
            'gender': gender,
            'headportrait': head,
            'token': token,
        }, 'users')
        if flag:
            return jsonify({'code': 1, 'msg': 'success', 'data': token})  # 成功返回
        else:
            return jsonify({'code': -1, 'msg': 'unable to insert'})
    else:
        if email_check['openid'] == '' or email_check['openid'] is None:
            if email_check['password'] != generate_password(password):
                return jsonify({'code': -4, 'msg': 'password error'})

            token = new_token()
            db.update({'email': email}, {'openid': openid, 'token': token}, 'users')
            return jsonify({'code': 1, 'msg': 'success', 'data': token})  # 成功返回
        else:
            return jsonify({'code': -3, 'msg': 'the email has already been used in weixin'})  # 成功返回


@app.route('/api/account/bind_email')
def bind_email():
    """
    绑定邮箱
    :return:
    """
    token = request.values.get('token')
    new_email = request.values.get('email')
    db = Database()
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'user is not login or exist'})

    result = db.update({'token': token}, {'email': new_email}, 'users')
    if not result:
        return jsonify({'code': -1, 'msg': 'unable to update'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/account/bind_phonenumber')
def bind_phonenumber():
    """
    绑定手机号
    :return:
    """
    token = request.values.get('token')
    new_phone = request.values.get('phonenumber')
    db = Database()
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'user is not login or exist'})

    result = db.update({'token': token}, {'phonenumber': new_phone}, 'users')
    if not result:
        return jsonify({'code': -1, 'msg': 'unable to update'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/account/get_user_group')
def get_user_group():
    """
    获取用户组信息
    :return:
    """
    return jsonify({'code': 1, 'msg': 'success', 'data': USER_GROUP})


@app.route('/api/account/check_code_login')
def check_code_login():
    """
    验证码免密支付
    :return:
    """
    code = request.values.get('code')
    account = request.values.get('account')
    target = ''
    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', account):
        target = 'email'
    elif re.match(r"^1[35678]\d{9}$", account):
        target = 'phonenumber'
    else:
        return jsonify({'code': 0, 'msg': 'error'})

    db = Database()
    user = db.get({target: account, 'check_code': code}, 'users')
    if user:
        data = {
            'user_id': user['userID'],
            'head_portrait': user['headportrait'],
            'group': get_group(user['usergroup']),
            'nickname': user['nickname'],
            'level': get_level(user['exp']),
            'exp': {'value': user['exp'], 'percent': user['exp'] / LEVEL_EXP[get_level(user['exp'])] * 100},
            'answer': db.count({'userID': user['userID']}, 'answers'),
            'follow': db.count({'userID': user['userID']}, 'followuser'),
            'fans': db.count({'target': user['userID']}, 'followuser')
        }
        result = db.update({target: account, 'check_code': code},
                           {'token': new_token(),
                            'last_login': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))},
                           'users')  # 更新token
        if result:
            return jsonify(
                {'code': 1, 'msg': 'success', 'data': {'token': result['token'], 'data': data}})
        return jsonify({'code': -1, 'msg': 'unable to update token'})  # 失败返回
    return jsonify({'code': 0, 'msg': 'unexpected user'})  # 失败返回


@app.route('/api/account/login', methods=['POST'])
def login():
    """
        用户登录
        :return: code(0=未知用户，-1=token初始化失败，1=成功)
        """
    username = request.form['username']
    password = request.form['password']
    # 字段名
    target = ''
    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', username):
        target = 'email'
    elif re.match(r"^1[35678]\d{9}$", username):
        target = 'phonenumber'
    else:
        return jsonify({'code': 0, 'msg': 'error'})

    db = Database()
    user = db.get({target: username, 'password': generate_password(password)}, 'users')
    if user:
        data = {
            'user_id': user['userID'],
            'head_portrait': user['headportrait'],
            'group': get_group(user['usergroup']),
            'nickname': user['nickname'],
            'level': get_level(user['exp']),
            'exp': {'value': user['exp'], 'percent': user['exp'] / LEVEL_EXP[get_level(user['exp'])] * 100},
            'answer': db.count({'userID': user['userID']}, 'answers'),
            'follow': db.count({'userID': user['userID']}, 'followuser'),
            'fans': db.count({'target': user['userID']}, 'followuser')
        }
        result = db.update({target: username, 'password': generate_password(password)},
                           {'token': new_token(),
                            'last_login': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))},
                           'users')  # 更新token
        if result:
            return jsonify(
                {'code': 1, 'msg': 'success', 'data': {'token': result['token'], 'data': data}})
        return jsonify({'code': -1, 'msg': 'unable to update token'})  # 失败返回
    return jsonify({'code': 0, 'msg': 'unexpected user'})  # 失败返回


@app.route('/api/account/register', methods=['POST'])
def register():
    """
    注册
    :return: code(-1=用户已存在，1=成功)
    """
    account = request.form['email']
    password = request.form['password']
    openid = ""
    nickname = ''
    gender = ""
    head = ""
    check = False
    dict_name = ""

    if 'nickname' in request.form.keys():
        nickname = request.form['nickname']
    if 'gender' in request.form.keys():
        gender = request.form['gender']
    if 'head' in request.form.keys():
        head = request.form['head']

    db = Database()
    if re.match(r'^[0-9a-zA-Z_]{0,19}@[0-9a-zA-Z]{1,13}\.[com,cn,net]{1,3}$', account):
        check = db.get({'email': account}, 'users')
        dict_name = "email"
    elif re.match(r"^1[35678]\d{9}$", account):
        check = db.get({'phonenumber': account}, 'users')
        dict_name = "phonenumber"
    else:
        return jsonify({'code': -3, 'msg': 'account format error,not email or phonenumber'})

    if not check:
        nick_name_list = random.sample('zyxwvutsrqponmlkjihgfedcba1234567890', 10)
        if nickname == '':
            nickname = '用户'
            for value in nick_name_list:
                nickname += value

        # 之后微信实装了在这里补上openid的注册
        flag = db.insert({
            dict_name: account,
            'password': generate_password(password),
            'nickname': nickname,
            'openid': openid,
            'gender': gender,
            'headportrait': head
        }, 'users')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})  # 成功返回
        else:
            return jsonify({'code': -2, 'msg': 'unable to insert'})
    return jsonify({'code': -1, 'msg': 'user has already exist'})  # 未知错误


@app.route('/api/account/set_account_info', methods=['POST'])
def set_account_info():
    """
    设置账户详情
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        nickname = request.form['nickname']
        description = request.form['description']
        headportrait = request.form['headportrait']

        flag = db.update({'token': token},
                         {'nickname': nickname, 'description': description,
                          'headportrait': headportrait}, 'users')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to update'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/check_email')
def check_email():
    """
    检测邮箱是否被注册
    :return: code(0=已经被注册，1=还未被注册)
    """
    email = request.values.get('email')
    db = Database()
    user = db.get({'email': email}, 'users')
    if user:
        return jsonify({'code': 0, 'msg': "the email had been registered"})
    else:
        return jsonify({'code': 1, 'msg': "the email can be registered"})


@app.route('/api/account/get_user')
def get_user():
    """
    根据user_id获取用户信息
    :return: code(0=未知用户，1=成功)
    """
    user_id = request.values.get('user_id')
    db = Database()
    user = db.get({'userID': user_id}, 'users')
    if user:
        data = {
            'user_id': user_id,
            'head_portrait': user['headportrait'],
            'user_group': user['usergroup'],
            'nickname': user['nickname'],
            'level': get_level(user['exp']),
            'exp': {'value': user['exp'], 'percent': user['exp'] / LEVEL_EXP[get_level(user['exp'])] * 100},
            'answer': db.count({'userID': user['userID']}, 'answers'),
            'follow': db.count({'userID': user['userID']}, 'followuser'),
            'fans': db.count({'target': user['userID']}, 'followuser'),
            'email': user['email'],
            'description': user['description'],
            'state': user['state'],
        }
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_user_by_token')
def get_user_by_token():
    """
    根据token获取用户信息
    :return:code(0=未知用户，1=成功)
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        data = {
            'user_id': user['userID'],
            'head_portrait': user['headportrait'],
            'group': get_group(user['usergroup']),
            'nickname': user['nickname'],
            'level': get_level(user['exp']),
            'exp': {'value': user['exp'], 'percent': user['exp'] / LEVEL_EXP[get_level(user['exp'])] * 100},
            'answer': db.count({'userID': user['userID']}, 'answers'),
            'follow': db.count({'userID': user['userID']}, 'followuser'),
            'fans': db.count({'target': user['userID']}, 'followuser'),
            'email': user['email'],
            'description': user['description'],
            'state': user['state'],
            'phonenumber': user['phonenumber'],
        }
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


def get_level(exp):
    i = 0
    while i < len(LEVEL_EXP):
        if LEVEL_EXP[i] > exp:
            return i
        i = i + 1
    return len(LEVEL_EXP)


def get_group(group):
    if group < len(USER_GROUP):
        return {'text': USER_GROUP[group], 'value': group}
    return {'text': '未知', 'value': group}


@app.route('/api/account/add_user_action')
def add_user_action():
    """
    添加用户行为
    :return: code(0=未知用户，-1=无法写入，1=成功)
    """
    token = request.values.get('token')
    action_type = request.values.get('action_type')
    target_id = request.values.get('target_id')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.insert({'userID': user['userID'], 'targettype': action_type, 'targetID': target_id}, 'useraction')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/follow_user')
def follow_user():
    """
    关注某个用户
    :return: code:-1 = 用户不存在, -2 = 被关注用户不存在, 0 = 关注失败, 1 = 关注成功
    """
    token = request.values.get('token')
    user_id = request.values.get('user_id')

    db = Database()
    user = db.get({'token': token}, 'users')
    followed_user = db.get({'userID': user_id}, 'users')

    if not user:
        return jsonify({'code': -1, 'msg': 'the user is not exist'})
    if not followed_user:
        return jsonify({'code': -1, 'msg': 'the followed_user is not exist'})

    success = db.insert({'userID': user['userID'], 'target': user_id}, 'followuser')
    if success:
        return jsonify({'code': 1, 'msg': 'follow success'})
    else:
        return jsonify({'code': 0, 'msg': 'there are something wrong when inserted the data into database'})


@app.route('/api/account/un_follow_user')
def un_follow_user():
    """
    取消关注用户
    :return:
    """
    user_id = request.values.get('user_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.delete({'userID': user['userID'], 'target': user_id}, 'followuser')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_user_follow_state')
def get_user_follow_state():
    """
    获取用户关注情况
    :return:
    """
    token = request.values.get('token')
    user_id = request.values.get('user_id')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.get({'userID': user['userID'], 'target': user_id}, 'followuser')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unfollow'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_my_follow')
def get_my_follow():
    """
    获取关注的人列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        follow = db.get({'userID': user['userID']}, 'followinfo', 0)
        data = []
        for value in follow:
            data.append({
                'id': value['target'],
                'nickname': value['target_nickname'],
                'description': value['target_description'],
                'head_portrait': value['target_headportrait'],
                'usergroup': get_group(value['target_usergroup']),
                'exp': value['target_exp'],
                'level': get_level(value['target_exp']),
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


def set_user_action(user_id, target, action_type):
    """
    设置用户行为
    :param user_id:用户id
    :param target: 目标id
    :param action_type: 行为种类
    :return: Boolean
    """
    db = Database()
    flag = db.insert({'userID': user_id, 'targetID': target, 'targettype': action_type}, 'useraction')
    if flag:
        return True
    return False


@app.route('/api/account/set_verify_info', methods=['POST'])
def set_verify_info():
    """
    上传实名信息
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        real_name = request.form['real_name']
        nationality = request.form['nationality']
        address = request.form['address']
        gender = request.form['gender']
        number = request.form['number']
        flag = db.update({'userID': user['userID']},
                         {'real_name': real_name, 'nationality': nationality, 'address': address, 'gender': gender,
                          'number': number, 'state': 1}, 'users')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to set'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_verify_user')
def get_verify_user():
    """
    获取待实名审核的用户
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.values.get('user_id')
        user = db.get({'userID': user_id}, 'users')
        if user:
            data = {
                'nickname': user['nickname'],
                'group': get_group(user['usergroup']),
                'level': get_level(user['exp']),
                'headportrait': user['headportrait'],
                'exp': user['exp'],
                'real_name': user['real_name'],
                'nationality': user['nationality'],
                'number': user['number'],
                'gender': user['gender'],
                'front_pic': user['front_pic'],
                'back_pic': user['back_pic'],
                'address': user['address']
            }
            return jsonify({'code': 1, 'msg': 'success', 'data': data})
        return jsonify({'code': -1, 'msg': 'unknown user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_verify_list')
def get_verify_list():
    """
    获取实名制的列表
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        users = db.get({}, 'users')
        wait = []
        confirm = []
        refuse = []
        for value in users:
            value.update({
                'create_time': value['create_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'last_login': value['last_login'].strftime('%Y-%m-%d %H:%M:%S')
            })
            if value['state'] == 1:
                wait.append(value)
            elif value['state'] == 2:
                confirm.append(value)
            elif value['state'] == 3:
                refuse.append(value)
        return jsonify({'code': 1, 'msg': 'success', 'data': {'wait': wait, 'confirm': confirm, 'refuse': refuse}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/verify', methods=['POST'])
def verify():
    """
    实名认证
    :return:
    """
    token = request.headers.get('X-Token')
    user_id = request.form['user_id']
    real_name = request.form['real_name']
    birthday = request.form['birthday']
    gender = request.form['gender']
    number = request.form['number']
    address = request.form['address']
    nationality = request.form['nationality']
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        flag = db.update({'userID': user_id}, {
            'real_name': real_name,
            'birthday': birthday,
            'gender': gender,
            'number': number,
            'address': address,
            'nationality': nationality,
            'state': 2
        }, 'users')
        set_user_action(user['userID'], user_id, 26)
        set_sys_message(user['userID'], 1, '你的实名认证申请已通过！', user_id, '实名认证')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to update'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/not_verify', methods=['POST'])
def not_verify():
    """
    实名认证不通过
    :return:
    """
    token = request.headers.get('X-Token')
    user_id = request.form['user_id']
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        flag = db.update({'userID': user_id}, {
            'real_name': '',
            'gender': '',
            'number': '',
            'address': '',
            'nationality': '',
            'state': 3
        }, 'users')
        set_user_action(user['userID'], user_id, 27)
        set_sys_message(user['userID'], 1, '你的实名认证申请未通过！', user_id, '实名认证')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to update'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_exp_change')
def get_exp_change():
    """
    获取积分变动详情
    :return: code(0=未知用户，1=成功)
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        exp_list = db.get({'userID': user['userID']}, 'exp_change')
        sorted(exp_list, key=lambda x: x['time'], reverse=True)
        return jsonify({'code': 1, 'msg': 'success', 'data': exp_list})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/set_exp_change')
def set_exp_change():
    """
    设置积分变动
    :return: code(0=未知用户，-1=更新失败，1=成功)
    """
    token = request.values.get('token')
    value = request.values.get('value')
    description = request.values.get('description')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.update({'token': token}, {'exp': int(user['exp']) + int(value)}, 'users')
        flag2 = db.insert({'value': value, 'userID': user['userID'], 'description': description}, 'exp_change')
        if flag and flag2:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


def set_exp(user_id, value, description):
    """
    内置的积分修改方法
    :return:
    """
    db = Database()
    user = db.get({'userID': user_id}, 'users')
    if user:
        flag = db.update({'userID': user_id}, {'exp': int(user['exp']) + int(value)}, 'users')
        flag2 = db.insert({'value': value, 'userID': user['userID'], 'description': description}, 'exp_change')
        if flag and flag2:
            return 1
        return -1
    return 0


@app.route('/api/account/back_get_users')
def back_get_users():
    """
    获取所有用户列表
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        users = db.get({}, 'users', 0)
        for value in users:
            value.update({
                'group': get_group(value['usergroup']),
                'level': get_level(value['exp']),
                'exp': {'value': value['exp'], 'percent': value['exp'] / LEVEL_EXP[get_level(value['exp'])] * 100},
                'answer': db.count({'userID': value['userID']}, 'answers'),
                'follow': db.count({'userID': value['userID']}, 'followuser'),
                'fans': db.count({'target': value['userID']}, 'followuser')
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': users})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/back_get_normal_users')
def back_get_normal_users():
    """
    获取一般从业者账户
    :return:code(0=未知用户，1=成功)
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        users = db.get({'usergroup': 1}, 'users', 0)
        wait = []
        confirm = []
        refuse = []
        un_identity = []
        banned = db.get({'usergroup': 4}, 'users', 0)
        all = users + banned
        for value in all:
            value.update({
                'group': get_group(value['usergroup']),
                'level': get_level(value['exp']),
                'exp': {'value': value['exp'], 'percent': value['exp'] / LEVEL_EXP[get_level(value['exp'])] * 100},
                'answer': db.count({'userID': value['userID']}, 'answers'),
                'follow': db.count({'userID': value['userID']}, 'followuser'),
                'fans': db.count({'target': value['userID']}, 'followuser'),
                'create_time': value['create_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'last_login': value['last_login'].strftime('%Y-%m-%d %H:%M:%S')
            })
            if value['state'] == 0:
                value.update({'status': '未实名'})
                un_identity.append(value)
            elif value['state'] == 1:
                value.update({'status': '审核中'})
                wait.append(value)
            elif value['state'] == 2:
                value.update({'status': '已通过'})
                confirm.append(value)
            elif value['state'] == 3:
                value.update({'status': '已拒绝'})
                refuse.append(value)
            else:
                pass
            if value['usergroup'] == 4:
                value.update({'status': '已封禁'})
        return jsonify({'code': 1, 'msg': 'success',
                        'data': {'all': users + banned, 'un_identity': un_identity, 'wait': wait, 'confirm': confirm,
                                 'refuse': refuse,
                                 'banned': banned}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/back_get_specialist_users')
def back_get_specialist_users():
    """
    获取一般从业者账户
    :return:code(0=未知用户，1=成功)
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        confirm = db.get({'usergroup': 2}, 'users', 0)
        wait = db.get({'usergroup': 5}, 'users', 0)
        for value in confirm + wait:
            value.update({
                'group': get_group(value['usergroup']),
                'level': get_level(value['exp']),
                'exp': {'value': value['exp'], 'percent': value['exp'] / LEVEL_EXP[get_level(value['exp'])] * 100},
                'answer': db.count({'userID': value['userID']}, 'answers'),
                'follow': db.count({'userID': value['userID']}, 'followuser'),
                'fans': db.count({'target': value['userID']}, 'followuser'),
                'create_time': value['create_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'last_login': value['last_login'].strftime('%Y-%m-%d %H:%M:%S')
            })
            if value['usergroup'] == 2:
                value.update({'status': '已审核'})
            elif value['usergroup'] == 5:
                value.update({'status': '待审核'})
        return jsonify({'code': 1, 'msg': 'success',
                        'data': {'all': confirm + wait, 'wait': wait, 'confirm': confirm}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/back_get_enterprise_users')
def back_get_enterprise_users():
    """
    获取一般从业者账户
    :return:code(0=未知用户，1=成功)
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        confirm = db.get({'usergroup': 3}, 'users', 0)
        wait = db.get({'usergroup': 6}, 'users', 0)
        for value in confirm + wait:
            value.update({
                'group': get_group(value['usergroup']),
                'level': get_level(value['exp']),
                'exp': {'value': value['exp'], 'percent': value['exp'] / LEVEL_EXP[get_level(value['exp'])] * 100},
                'answer': db.count({'userID': value['userID']}, 'answers'),
                'follow': db.count({'userID': value['userID']}, 'followuser'),
                'fans': db.count({'target': value['userID']}, 'followuser'),
                'create_time': value['create_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'last_login': value['last_login'].strftime('%Y-%m-%d %H:%M:%S')
            })
            if value['usergroup'] == 3:
                value.update({'status': '已审核'})
            elif value['usergroup'] == 6:
                value.update({'status': '待审核'})
        return jsonify({'code': 1, 'msg': 'success',
                        'data': {'all': confirm + wait, 'wait': wait, 'confirm': confirm}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_specialist_info')
def get_specialist_info():
    """
    获取专家申请人的个人消息
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.values.get('user_id')
        user = db.get({'userID': user_id}, 'users')
        if user:
            data = {
                'nickname': user['nickname'],
                'group': get_group(user['usergroup']),
                'level': get_level(user['exp']),
                'headportrait': user['headportrait'],
                'exp': user['exp'],
                'specialitst_license': user['specialitst_license'],
                'license_type': user['license_type'],
                'real_name': user['real_name'],
                'nationality': user['nationality'],
                'number': user['number'],
                'gender': user['gender'],
                'address': user['address']
            }
            return jsonify({'code': 1, 'msg': 'success', 'data': data})
        return jsonify({'code': -1, 'msg': 'unknown user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/confirm_specialist')
def confirm_specialist():
    """
    确认专家身份
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.values.get('user_id')
        specialist = db.get({'userID': user_id, 'usergroup': 5}, 'users')
        if specialist:
            flag = db.update({'userID': user_id}, {'usergroup': 2}, 'users')
            set_user_action(user['userID'], user_id, 28)
            set_sys_message(user['userID'], 1, '你的专家认证申请已通过！', user_id, '专家认证')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to upgrade'})
        return jsonify({'code': -2, 'msg': 'unexpected specialist'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/refuse_specialist')
def refuse_specialist():
    """
    确认专家身份
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.values.get('user_id')
        specialist = db.get({'userID': user_id, 'usergroup': 5}, 'users')
        if specialist:
            flag = db.update({'userID': user_id}, {'usergroup': 1}, 'users')
            set_user_action(user['userID'], user_id, 29)
            set_sys_message(user['userID'], 1, '你的专家认证申请未通过！', user_id, '专家认证')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to upgrade'})
        return jsonify({'code': -2, 'msg': 'unexpected specialist'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/confirm_enterprise')
def confirm_enterprise():
    """
    确认企业身份
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.values.get('user_id')
        specialist = db.get({'userID': user_id, 'usergroup': 6}, 'users')
        if specialist:
            flag = db.update({'userID': user_id}, {'usergroup': 3}, 'users')
            set_user_action(user['userID'], user_id, 30)
            set_sys_message(user['userID'], 1, '你的企业认证申请已通过！', user_id, '企业认证')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to upgrade'})
        return jsonify({'code': -2, 'msg': 'unexpected enterprise'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/refuse_enterprise')
def refuse_enterprise():
    """
    确认企业身份
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.values.get('user_id')
        specialist = db.get({'userID': user_id, 'usergroup': 6}, 'users')
        if specialist:
            flag = db.update({'userID': user_id}, {'usergroup': 1}, 'users')
            set_user_action(user['userID'], user_id, 31)
            set_sys_message(user['userID'], 1, '你的企业认证申请未通过！', user_id, '企业认证')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to upgrade'})
        return jsonify({'code': -2, 'msg': 'unexpected enterprise'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/delete_user')
def delete_user():
    """
    清除用户
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.values.get('user_id')
        flag = db.update({'userID': user_id}, {'usergroup': 4}, 'users')
        set_user_action(user['userID'], user_id, 32)
        set_sys_message(user['userID'], 1, '你已被管理员封禁！', user_id, '账户封禁')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/change_user', methods=['POST'])
def change_user():
    """
    修改用户信息
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        user_id = request.form['user_id']
        nickname = request.form['nickname']
        headportrait = request.form['headportrait']
        usergroup = request.form['usergroup']
        exp = request.form['exp']
        update = {
            'nickname': nickname,
            'headportrait': headportrait,
            'usergroup': usergroup,
            'exp': exp
        }
        flag = db.update({'userID': user_id}, update, 'users')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_account_balance', methods=['POST'])
def get_account_balance():
    """
    获取用户的钱包余额
    :return: code:0=用户不存在  1=获取成功
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        account_balance = db.sql("select sum(amount) as balance from pay_log where `from`='%s'" % (user['userID']))
        if account_balance:
            account_balance = account_balance[0]['balance']
        else:
            account_balance = 0
        return jsonify({'code': 1, 'msg': 'success', 'data': account_balance})
    return jsonify({'code': 0, 'msg': 'the user is not exist'})


@app.route('/api/account/add_account_balance', methods=['POST'])
def add_account_balance():
    """
    增加用户的钱包余额
    :return:code:0=数据库操作失败  1=增加成功  -2=用户不存在
    """
    # 要增加的量
    num = request.form['num']
    token = request.form['token']
    res = change_account_balance(num, token)
    db = Database()
    user = db.get({'token': token}, 'users')
    Flag = False
    if user:
        flag = db.insert({'from': user['userID'], 'amount': float(num), 'type': 8, 'receive': 0}, 'pay_log')
    if res == 1 and flag:
        return jsonify({'code': 1, 'msg': 'success'})
    elif res == 0:
        return jsonify({'code': 0, 'msg': 'there are something wrong when operate the database'})
    elif res == -2 or not flag:
        return jsonify({'code': -2, 'msg': 'the user is not exist'})


@app.route('/api/account/minus_account_balance', methods=['POST'])
def minus_account_balance():
    """
    减少用户的钱包余额
    :return:code:-2=用户不存在  -1=余额不足  0=数据库操作失败  1=成功
    """
    # 要减少的量
    num = request.form['num']
    # 减少的量在计算时应该为负数
    num = -num
    token = request.form['token']
    res = change_account_balance(num, token)
    db = Database()
    user = db.get({'token': token}, 'users')
    flag = False
    if user:
        flag = db.insert({'from': user['userID'], 'amount': -float(num), 'type': 9, 'receive': 0}, 'pay_log')
    if res == 1 and flag:
        return jsonify({'code': 1, 'msg': 'success'})
    elif res == 0:
        return jsonify({'code': 0, 'msg': 'there are something wrong when operate the database'})
    elif res == -2 or not flag:
        return jsonify({'code': -2, 'msg': 'the user is not exist'})
    elif res == -1:
        return jsonify({'code': -1, 'msg': 'account balance not enough'})


@app.route('/api/account/history_pay', methods=['POST'])
def history_pay():
    """
    获取用户的支付记录
    :return: code: 0=用户不存在 1=成功
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': -1, 'msg': 'the user is not exist'})

    log = db.get({'from': user['userID']}, 'pay_log', 0)
    for value in log:
        value.update({
            'time': value['time'].strftime("%Y-%m-%d"),
            'type_name': PAY_DICT[int(value['type']) - 1]
        })
    return jsonify({'code': 1, 'msg': 'success', 'data': log})


@app.route('/api/account/weixin_pay_api')
def weixin_pay_api():
    appid = 'wxe1e434222057b10e'
    body = '商品'
    mch_id = '1517624211'
    KEY = '11111111111111111111111111111111'
    nonce_str = randomkeys(32)
    if 'nonce_str' in request.values.keys():
        nonce_str = request.values.get('nonce_str')

    notify_url = 'http://www.weixin.qq.com/wxpay/pay.php'
    out_trade_no = randomkeys(24)
    spbill_create_ip = '104.224.168.56'
    trade_type = 'JSAPI'

    user_openid = request.values.get('openid')
    total_fee = request.values.get('total_fee')

    post_data = {
        'appid': appid,
        'body': body,
        'mch_id': mch_id,
        'nonce_str': nonce_str,
        'notify_url': notify_url,
        'openid': user_openid,
        'out_trade_no': out_trade_no,
        'spbill_create_ip': spbill_create_ip,  # 服务器终端ip
        'total_fee': total_fee,  # 总金额
        'trade_type': trade_type
    }
    sign = MakeSign(post_data, KEY)
    post_xml = "<xml><appid>" + appid + "</appid>"
    post_xml += "<body>" + body + "</body>"
    post_xml += "<mch_id>" + mch_id + "</mch_id>"
    post_xml += "<nonce_str>" + nonce_str + "</nonce_str>"
    post_xml += "<notify_url>" + notify_url + "</notify_url>"
    post_xml += "<openid>" + user_openid + "</openid>"
    post_xml += "<out_trade_no>" + out_trade_no + "</out_trade_no>"
    post_xml += "<spbill_create_ip>" + spbill_create_ip + "</spbill_create_ip>"
    post_xml += "<total_fee>" + total_fee + "</total_fee>"
    post_xml += "<trade_type>" + trade_type + "</trade_type>"
    post_xml += "<sign>" + sign + "</sign></xml>"

    url = 'https://api.mch.weixin.qq.com/pay/unifiedorder';
    req = requests.post("https://api.mch.weixin.qq.com/pay/unifiedorder",
                        data=post_xml.encode('utf-8'),
                        headers={'Content-Type': 'text/xml'})
    msg = req.text.encode('ISO-8859-1').decode('utf-8')
    xml_dict = xml_to_dict(msg)
    data = {}
    if xml_dict['RETURN_CODE'] == 'SUCCESS' and xml_dict['RESULT_CODE'] == 'SUCCESS':
        tmp = {}

        tmp['appid'] = appid
        data['text'] = "正确"
        tmp['nonceStr'] = nonce_str
        tmp['package'] = 'prepay_id=' + xml_dict['PREPAY_ID']
        tmp['timeStamp'] = int(time.time())
        data['state'] = 1
        data['timeStamp'] = int(time.time())
        data['nonceStr'] = nonce_str
        data['signType'] = 'MD5'
        data['package'] = 'prepay_id=' + xml_dict['PREPAY_ID']
        data['paySign'] = MakeSign(tmp, KEY)
        data['out_trade_no'] = out_trade_no
    else:
        data['state'] = 0
        data['text'] = "错误"
        data['RETURN_CODE'] = xml_dict['RETURN_CODE']
        data['RETURN_MSG'] = xml_dict['RETURN_MSG']

    return jsonify({'code': data['state'], 'msg': data['text'], 'data': data})


def toUrlParams(param):
    """
    将参数拼接为url: key=value&key=value
    :param param:
    :return:
    """
    string = "";
    if param:
        arr = []
        for key in param.keys():
            arr.append(key + "=" + str(param[key]))
        string = '&'.join(arr)
    return string


def randomkeys(num):
    """
    生成指定长度的随机数字串
    :param num:
    :return:
    """
    string = ""
    for i in range(0, num):
        string += str(random.randint(0, 9))
    return string


def xml_to_dict(xml_data):
    """
    xml转换为字典
    :param xml_data:
    :return:
    """
    soup = BeautifulSoup(xml_data, features='xml')
    xml = soup.find('xml')
    if not xml:
        return {}
    # 将 XML 数据转化为 Dict
    data = dict([(item.name, item.text) for item in xml.find_all()])
    return data


def MakeSign(post, key):
    string = toUrlParams(post)
    string = string + "&key=" + str(key)
    h = hashlib.md5()
    h.update(bytes(string, encoding='utf-8'))
    result = h.hexdigest()

    return result


def change_account_balance(num, token):
    """
    增加或减少余额值
    :param num: 改变量
    :param token: 用户token
    :return: code:-2=用户不存在  -1=余额不足  0=数据库操作失败  1=改变成功
    """
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        # 若num为负数，钱包可能被扣到负值
        if float(user['account_balance']) + float(num) < 0:
            return -1

        flag = db.update_new({'userID': user['userID']},
                             {'account_balance': round(float(user['account_balance']) + float(num), 2)},
                             'users')
        if flag:
            return 1
        return 0
    return -2


@app.route('/api/account/get_collections')
def get_collections():
    """
    获取收藏信息
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answers = db.get({'userID': user['userID']}, 'collect_answer_info', 0)
        answers_data = []
        for value in answers:
            answers_data.append({
                'title': value['title'],
                'headline': value['content'],
                'action': '',
                'subtitle': str(db.count({'targettype': 1, 'targetID': value['answerID']},
                                         'useraction')) + ' 点赞 · ' + str(db.count({'answerID': value['answerID']},
                                                                                  'answercomments')) + ' 评论',
                'id': value['answerID']
            })
        questions = db.get({'userID': user['userID']}, 'followquestion_info', 0)
        questions_data = []
        for value in questions:
            questions_data.append({
                'title': value['title'],
                'headline': value['description'],
                'action': '',
                'subtitle': str(db.count({'questionID': value['target']}, 'answers')) + ' 回答 · ' + str(
                    db.count({'questionID': value['target']}, 'questioncomments')) + ' 评论',
                'id': value['target']
            })
        articles = db.get({'userID': user['userID']}, 'collect_article_info', 0)
        articles_data = []
        for value in articles:
            articles_data.append({
                'title': value['title'],
                'headline': value['content'],
                'subtitle': '',
                'action': '',
                'id': value['articleID']
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': [answers_data, questions_data, articles_data]})


@app.route('/api/account/get_history')
def get_history():
    """
    获取历史纪录
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answers = db.get({'userID': user['userID']}, 'history_answers', 0)
        questions = db.get({'userID': user['userID']}, 'history_questions', 0)
        articles = db.get({'userID': user['userID']}, 'history_articles', 0)
        answers = sorted(answers, reverse=True, key=lambda a: a['actiontime'])
        questions = sorted(questions, reverse=True, key=lambda a: a['actiontime'])
        articles = sorted(articles, reverse=True, key=lambda a: a['actiontime'])
        for value in answers + questions + articles:
            value.update({'tags': get_tags(value['tags'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': [answers, questions, articles]})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_user_answers_by_id')
def get_user_answers_by_id():
    """
    获取用户的回答
    :return:
    """
    user_id = request.values.get('user_id')
    db = Database()
    user = db.get({'userID': user_id}, 'users')
    if user:
        answers = db.get({'userID': user['userID']}, 'answersinfo', 0)
        for value in answers:
            value.update({'tags': get_tags(value['tags'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': answers})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_user_questions_by_id')
def get_user_questions_by_id():
    """
    获取用户的问题
    :return:
    """
    user_id = request.values.get('user_id')
    db = Database()
    user = db.get({'userID': user_id}, 'users')
    if user:
        questions = db.get({'userID': user['userID']}, 'questions', 0)
        for value in questions:
            value.update({'tags': get_tags(value['tags']),
                          'follow': db.count({'targetID': value['questionID'], 'targettype': 12}, 'useraction'),
                          'comments': db.count({'questionID': value['questionID']}, 'questioncomments')})
        return jsonify({'code': 1, 'msg': 'success', 'data': questions})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/account/get_user_articles_by_id')
def get_user_articles_by_id():
    """
    获取用户的文章
    :return:
    """
    user_id = request.values.get('user_id')
    db = Database()
    user = db.get({'userID': user_id}, 'users')
    if user:
        articles = db.get({'userID': user['userID']}, 'articleinfo', 0)
        for value in articles:
            value.update({'tags': get_tags(value['tags'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': articles})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    问题接口
"""


@app.route('/api/questions/add_question', methods=['POST'])
def add_question():
    """
    添加问题
    :return:code(0=未知用户，-1=无法添加问题，1=成功)
    """
    token = request.form['token']
    title = request.form['title']
    description = request.form['description']
    tags = request.form['tags']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.insert({'title': title, 'description': description, 'userID': user['userID'], 'tags': tags},
                         'questions')
        if flag:
            set_exp(user['userID'], 3, '发布话题')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert question'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/questions/add_priced_question', methods=['POST'])
def add_priced_question():
    """
    添加付费问题
    :return:code(-2=用户不存在  -1=余额不足  0=数据库操作失败  1=成功)
    """
    token = request.form['token']
    price = request.form['price']
    db = Database()
    res = change_account_balance(-float(price), token)
    if res == 1:
        user = db.get({'token': token}, 'users')
        if user:
            title = request.form['title']
            description = request.form['description']
            tags = request.form['tags']
            allowed_user = request.form['allowed_user']
            flag = db.insert({'title': title, 'description': description, 'userID': user['userID'], 'tags': tags,
                              'allowed_user': allowed_user, 'question_type': 1},
                             'questions')
            if flag:
                set_exp(user['userID'], 4, '发布付费话题')
                return jsonify({'code': 1, 'msg': 'success'})
            change_account_balance(-float(price), token)
            return jsonify({'code': 0, 'msg': 'there are something wrong when operate the database'})
        return jsonify({'code': -2, 'msg': 'the user is not exist'})
    elif res == 0:
        return jsonify({'code': 0, 'msg': 'there are something wrong when operate the database'})
    elif res == -2:
        return jsonify({'code': -2, 'msg': 'the user is not exist'})
    elif res == -1:
        return jsonify({'code': -1, 'msg': 'account balance not enough'})


@app.route('/api/questions/adopt_answer')
def adopt_answer():
    """
    针对付费问题采纳回答
    :return: code(0=未知用户，-4=不能找到回答，-3=不能找到问题，-2=未知答题人，-1=无法写入，1=成功)
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer_id = request.values.get('answer_id')
        answer = db.get({'answerID': answer_id}, 'answers')
        if answer:
            question = db.get({'questionID': answer['questionID']}, 'questions')
            if question:
                if question['userID'] == user['userID']:
                    flag = db.get({'userID': answer['userID']}, 'users')
                    if flag:
                        flag1 = db.update_new({'userID': answer['userID']},
                                              {'account_balance': float(flag['account_balance']) + float(
                                                  question['price'])},
                                              'users')
                        flag2 = db.update({'answerID': answer['answerID']}, {'answertype': 2}, 'answers')
                        if flag1 and flag2:
                            return jsonify({'code': 1, 'msg': 'success'})
                        return jsonify({'code': -1, 'msg': 'unable to update'})
                    return jsonify({'code': -2, 'msg': 'unexpected answer user'})
                return jsonify({'code': 0, 'msg': 'unexpected user'})
            return jsonify({'code': -3, 'msg': 'cannot find question'})
        return jsonify({'code': -4, 'msg': 'cannot find answer'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/questions/get_questions')
def get_questions():
    """
    获取问题
    :return:code(0=未知用户，-1=无法添加问题，1=成功)
    """
    db = Database()
    data = db.get({'state': 0}, 'questionsinfo', 0) + db.get({'state': 1}, 'questionsinfo', 0)
    return jsonify({'code': 0, 'msg': '', 'data': data})


@app.route('/api/questions/get_question')
def get_question():
    """
    通过id获取问题
    :return: code(0=未知问题，-1=未知提问人，1=成功)
    """
    question_id = request.values.get('question_id')
    db = Database()
    question = db.get({'questionID': question_id, 'state': 0}, 'questions')
    if question:
        user = db.get({'userID': question['userID']}, 'users')
        if user:
            data = {
                'question_id': question_id,
                'user_id': question['userID'],
                'user_nickname': user['nickname'],
                'user_headportrait': user['headportrait'],
                'title': question['title'],
                'description': question['description'],
                'tags': get_tags(question['tags']),
                'question_type': question['question_type'],
                'follow': db.count({'target': question_id}, 'followtopic'),
                'comment': db.count({'questionID': question_id}, 'questioncomments'),
                'price': question['price'],
                'answer': db.count({'questionID': question_id}, 'answers')
            }
            return jsonify({'code': 1, 'msg': 'success', 'data': data})
        return jsonify({'code': -1, 'msg': 'unknown user'})
    return jsonify({'code': 0, 'msg': 'unknown question'})


@app.route('/api/questions/get_follow')
def get_follow_question():
    """
    获取问题是否被收藏
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        question_id = request.values.get('question_id')
        follow = db.get({'userID': user['userID'], 'target': question_id}, 'followtopic')
        if follow:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unfollowed'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/questions/follow_question')
def follow_question():
    """
    关注某个问题
    :return: code:-1 = 问题不存在, -2 = 用户不存在, 0 = 关注失败, 1 = 关注成功
    """
    token = request.values.get('token')
    question_id = request.values.get('question_id')

    db = Database()
    user = db.get({'token': token}, 'users')
    question = db.get({'questionID': question_id}, 'questions')

    if not question:
        return jsonify({'code': -1, 'msg': "the question is not exist"})
    if not user:
        return jsonify({'code': -2, 'msg': "the user is not exist"})

    user_id = user['userID']
    success = db.insert({'userID': user_id, 'target': question_id}, 'followtopic')
    set_user_action(user_id, question_id, 12)
    if success:
        set_exp(question['questionID'], 2, '话题被收藏')
        return jsonify({'code': 1, 'msg': "follow success"})
    else:
        return jsonify({'code': 0, 'msg': "there are something wrong when inserted the data into database"})


@app.route('/api/questions/un_follow_question')
def un_follow_question():
    """
    取消关注某个问题
    :return: code:-1 = 问题不存在, -2 = 用户不存在, 0 = 关注失败, 1 = 关注成功
    """
    token = request.values.get('token')
    question_id = request.values.get('question_id')

    db = Database()
    user = db.get({'token': token}, 'users')
    question = db.get({'questionID': question_id}, 'questions')

    if not question:
        return jsonify({'code': -1, 'msg': "the question is not exist"})
    if not user:
        return jsonify({'code': -2, 'msg': "the user is not exist"})

    user_id = user['userID']
    success = db.delete({'userID': user_id, 'target': question_id}, 'followtopic')
    db.delete({'userID': user_id, 'targetID': question_id, 'targettype': 12}, 'useraction')
    if success:
        set_exp(question['questionID'], 2, '话题被收藏')
        return jsonify({'code': 1, 'msg': "follow success"})
    else:
        return jsonify({'code': 0, 'msg': "there are something wrong when inserted the data into database"})


@app.route('/api/questions/get_answer_list')
def get_answer_list():
    """
    根据问题id获取回答列表（倒序）
    :return: code(0=未知问题，1=成功)
    """
    question_id = request.args.get('question_id', type=str)
    db = Database()
    question = db.get({'questionID': question_id}, 'questions')
    if question:
        # answer_list = db.get({'questionID': question_id}, 'answers', 0)
        answer_list = db.get({'questionID': question_id, 'state': 0}, 'answersinfo', 0) + db.get(
            {'questionID': question_id, 'state': 1}, 'answersinfo', 0)
        for answer in answer_list:
            answer['edittime'] = get_formative_datetime(answer['edittime'])
            pattern = re.compile(r'<[Ii][Mm][Gg].+?/?>')
            answer.update({'image': pattern.findall(answer['content'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': answer_list})
    return jsonify({'code': 0, 'msg': 'unknown question'})


@app.route('/api/questions/get_answer_by_id')
def get_answer_by_id():
    answer_id = request.values.get('answer_id')
    db = Database()
    answer = db.get({'answerID': answer_id}, 'answers')
    if answer:
        user = db.get({'userID': answer['userID']}, 'users')
        if user:
            return jsonify({'code': 1, 'msg': 'success', 'data': {'author': user, 'item': answer}})
        return jsonify({'code': 0, 'msg': 'user is not exist'})
    return jsonify({'code': -1, 'msg': 'comment is not exist'})


@app.route('/api/questions/get_question_by_id')
def get_answer_by_id():
    q_id = request.values.get('question_id')
    db = Database()
    question = db.get({'questionID': q_id}, 'questions')
    if question:
        user = db.get({'userID': question['userID']}, 'users')
        if user:
            return jsonify({'code': 1, 'msg': 'success', 'data': {'author': user, 'item': question}})
        return jsonify({'code': 0, 'msg': 'user is not exist'})
    return jsonify({'code': -1, 'msg': 'comment is not exist'})


@app.route('/api/questions/get_priced_answer_list')
def get_priced_answer_list():
    """
    获取付费问题的回答
    :return: code:-2=问题不存在  -1=用户不存在  0=未付费  1=成功
    """
    # 获取问题ID和用户ID
    question_id = request.values.get('question_id')
    user_token = request.values.get('token')
    # 获取问题和用户信息
    db = Database()
    question = db.get({'questionID': question_id, 'question_type': 1}, 'questions')
    user = db.get({'token': user_token}, 'users')
    # 检查用户和问题是否存在
    if not question:
        return jsonify({'code': -2, 'msg': 'the question is not exist'})
    if not user:
        return jsonify({'code': -1, 'msg': 'the user is not exist'})

    user_id = user['userID']
    # 获取该问题,由该用户付费的记录
    payer = db.get({'receive': question_id, 'from': user_id, 'type': 1}, 'pay_log')
    # 获取是否为作者本人
    is_author = (user_id == question['userID'])

    # 已支付的或者提问者本人可以直接查看问题下的答案
    if payer or is_author:
        answers = db.get({'questionID': question_id}, 'answersinfo', 0)
        for answer in answers:
            answer['edittime'] = get_formative_datetime(answer['edittime'])
            pattern = re.compile(r'<[Ii][Mm][Gg].+?/?>')
            answer.update({'image': pattern.findall(answer['content'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': answers})
    # 未支付用户则无权限获取答案
    return jsonify({'code': 0, 'msg': 'the user have not paid this question'})


@app.route("/api/questions/get_answer_by_userid")
def get_answer_by_userid():
    """
    根据userid获取回答
    :return: code 0-获取失败  1-获取成功
    """
    user_id = request.values.get("user_id")
    db = Database()
    answer = db.get({'userID': user_id}, 'answers')
    return jsonify({'code': 1, 'msg': 'success', 'data': answer})


@app.route('/api/questions/pay_question')
def pay_question():
    """
    支付某一付费问题
    :return: code:-5=退钱失败  -4=创建支付记录失败  -3=问题不存在  -2=用户不存在  -1=余额不足  0=支付失败  1=成功
    """
    # 获取问题ID和用户ID
    question_id = request.values.get('question_id')
    user_token = request.values.get('token')
    # 获取问题和用户信息
    db = Database()
    question = db.get({'questionID': question_id}, 'questions')
    user = db.get({'token': user_token}, 'users')
    # 检查用户和问题是否存在
    if not question:
        return jsonify({'code': -3, 'msg': 'the question is not exist'})
    if not user:
        return jsonify({'code': -2, 'msg': 'the user is not exist'})

    # 试图扣钱,将价格取负数
    result = change_account_balance(-question['price'] * 0.05, user_token)
    # 余额不足，提示
    if result == -1:
        return jsonify({'code': -1, 'msg': 'account balance not enough'})
    # 支付的扣钱操作失败时，提示
    elif result == 0:
        return jsonify({'code': 0, 'msg': 'there are something wrong when paying'})
    # 支付成功，生成支付记录
    elif result == 1:
        res = db.insert(
            {'from': user['userID'], 'receive': question_id, 'amount': -question['price'] * 0.05, 'type': 1},
            'pay_log')
        if not res:
            # 若创建支付记录失败，视为支付失败，将钱退还
            return_money = change_account_balance(question['price'], user_token)
            # 若退还失败，提示与客服沟通取钱
            if return_money != 1:
                jsonify({'code': -5, 'msg': 'create the pay_log fail,please call 客服 to get your money back'})
            # 退还成功，提示支付记录创建失败，未能完成支付
            return jsonify({'code': -4, 'msg': 'paying fail,there are something wrong when create the pay_log'})
        # 支付成功
        set_exp(user['userID'], 4, '阅读付费话题')
        return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/questions/add_question_comment', methods=['POST'])
def add_question_comment():
    """
    添加评论
    :return:code(0=未知用户，-1=未知问题，-2=无法添加评论，1=成功)
    """
    question_id = request.form['question_id']
    content = request.form['content']
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'questionID': question_id}, 'questions')
        if answer:
            flag = db.insert({'userID': user['userID'], 'content': content, 'questionID': question_id},
                             'questioncomments')
            if flag:
                set_exp(user['userID'], 2, '评论话题')
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -2, 'msg': 'unable to insert comment'})
        return jsonify({'code': -1, 'msg': 'unable to find question'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/questions/get_comment_by_user_id')
def get_comment_by_user_id():
    user_id = request.values.get("user_id")
    db = Database()
    comments = db.get({'userID': user_id}, 'questioncomments')
    return jsonify({'code': 1, 'msg': 'success', 'data': comments})


@app.route('/api/questions/get_question_comment')
def get_question_comment():
    """
    获取问题评论
    :return: code(0=未知问题，1=成功)
    """
    question_id = request.values.get('question_id')
    db = Database()
    question = db.get({'questionID': question_id}, 'questions')
    if question:
        data = db.get({'questionID': question_id}, 'question_comments_info', 0)
        for value in data:
            value.update({'usergroup': get_group(value['usergroup']), 'level': get_level(value['exp']),
                          'createtime': value['createtime'].strftime('%Y-%m-%d %H:%M:%S'),
                          'ID':value['qcommentID']})
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unknown question'})

@app.route('/api/questions/get_question_comment_by_id')
def get_question_comment_by_id():
    """
    获取问题评论
    :return: code(0=未知问题，1=成功)
    """
    comment_id = request.values.get('comment_id')
    db = Database()
    comment = db.get({'qcommentID': comment_id}, 'questioncomments')
    if comment:
        user = db.get({'userID':comment['userID']}, 'users')
        if user:
            return jsonify({'code': 1, 'msg': 'success', 'data': {'author': user, 'item': comment}})
        return jsonify({'code': 0, 'msg': 'user is not exist'})
    return jsonify({'code': -1, 'msg': 'comment is not exist'})


@app.route('/api/questions/agree_question_comment')
def agree_question_comment():
    """
    对特定评论点赞
    :return: code(0=未知用户，-1=未知评论，-2=不能记录用户行为，-3=不能更新点赞数，1=成功)
    """
    comment_id = request.values.get('comment_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'qcommentID': comment_id}, 'questioncomments')
        if answer:
            result = db.update({'qcommentID': comment_id}, {'agree': int(answer['agree']) + 1}, 'questioncomments')
            flag = db.insert({'userID': user['userID'], 'targetID': comment_id, 'targettype': 5}, 'useraction')
            if result and flag:
                return jsonify({'code': 1, 'msg': 'success'})
            if result:
                return jsonify({'code': -2, 'msg': 'unable to insert user action'})
            if flag:
                return jsonify({'code': -3, 'msg': 'unable to update agree number'})
        return jsonify({'code': -1, 'msg': 'unknown comment'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/questions/back_get_questions')
def back_get_questions():
    """
    后台用查看所有问题
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        questions = db.get({}, 'questionsinfo', 0)
        data = []
        deleted = []
        wait = []
        for value in questions:
            if value['state'] == 0:
                status = '正常'
            elif value['state'] == -1:
                status = '已清除'
            elif value['state'] == 1:
                status = '待审核'
            else:
                status = '其他'
            item = {
                'questionID': value['questionID'],
                'description': value['description'],
                'title': value['title'],
                'edittime': value['edittime'].strftime('%Y-%m-%d %H:%M:%S'),
                'userID': value['userID'],
                'tags': get_tags(value['tags']),
                'nickname': value['nickname'],
                'state': value['state'],
                'status': status
            }
            data.append(item)
            if item['state'] == -1:
                deleted.append(item)
            elif item['state'] == 1:
                wait.append(item)
        return jsonify({'code': 1, 'msg': 'success', 'data': {'all': data, 'wait': wait, 'deleted': deleted}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/questions/delete_question')
def delete_question():
    """
    清除问题
    :return:
    """
    token = request.headers.get('X-Token')
    question_id = request.values.get('question_id')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        flag = db.update({'questionID': question_id}, {'state': -1}, 'questions')
        if flag:
            set_user_action(user['userID'], question_id, 34)
            set_sys_message(user['userID'], 1, '您发布的问题 ' + flag['title'] + ' 已被管理员清除！', flag['userID'], '问题清除')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/questions/get_my_questions')
def get_my_questions():
    """
    获取自己的问题
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        questions = db.get({'userID': user['userID']}, 'questions', 0)
        for value in questions:
            value.update({'tags': get_tags(value['tags']),
                          'follow': db.count({'targetID': value['questionID'], 'targettype': 12}, 'useraction'),
                          'comments': db.count({'questionID': value['questionID']}, 'questioncomments')})
        return jsonify({'code': 1, 'msg': 'success', 'data': questions})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    答案接口
"""


@app.route('/api/answer/add_answer', methods=['POST'])
def add_answer():
    """
    添加新的回答
    :return:code(0=未知用户，-1=未知问题，-2=无法添加回答，1=成功)
    """
    question_id = request.form['question_id']
    token = request.form['token']
    content = request.form['content']
    answer_type = request.form['answer_type']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        question = db.get({'questionID': question_id}, 'questions')
        if question:
            flag = db.insert(
                {'content': content, 'userID': user['userID'], 'questionID': question_id, 'answertype': answer_type},
                'answers')
            if flag:
                set_exp(user['userID'], 5, '发布回答')
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -2, 'msg': 'unable to insert answer'})
        return jsonify({'code': -1, 'msg': 'unknown question'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/add_priced_answer')
def add_priced_answer():
    """
    对付费问题添加回答
    :return:
    """
    question_id = request.form['question_id']
    token = request.form['token']
    content = request.form['content']
    answer_type = request.form['answer_type']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        question = db.get({'questionID': question_id}, 'questions')
        if question:
            allowed_user = question['allowed_user'].split(',')
            if user['usergroup'] in allowed_user:
                flag = db.insert(
                    {'content': content, 'userID': user['userID'], 'questionID': question_id,
                     'answertype': answer_type},
                    'answers')
                if flag:
                    set_exp(user['userID'], 7, '发布付费回答')
                    return jsonify({'code': 1, 'msg': 'success'})
                return jsonify({'code': -2, 'msg': 'unable to insert answer'})
            return jsonify({'code': -3, 'msg': 'you are not allowed to answer'})
        return jsonify({'code': -1, 'msg': 'unknown question'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


def get_tags(tags):
    """
    获取标签
    :param tags:字符串
    :return: 标签列表
    """
    if tags:
        tag_list = tags.split(',')
        db = Database()
        data = []
        for value in tag_list:
            tag = db.get({'id': value}, 'tags')
            if tag:
                data.append({'text': tag['name'], 'id': value})
        return data
    return ''


@app.route('/api/answer/get_answer')
def get_answer():
    """
    获取特定id的回答
    :return:code(0=未知回答，1=成功)
    """
    answer_id = request.values.get('answer_id')
    db = Database()
    answer = db.get({'answerID': answer_id}, 'answers')
    if answer and answer['state'] != -1:
        user = db.get({'userID': answer['userID']}, 'users')
        question = db.get({'questionID': answer['questionID']}, 'questions')
        if user:
            data = {
                'id': answer['answerID'],
                'user_id': answer['userID'],
                'user_nickname': user['nickname'],
                'user_headportrait': user['headportrait'],
                'content': answer['content'],
                'edit_time': get_formative_datetime(answer['edittime']),
                'agree': answer['agree'],
                'disagree': answer['disagree'],
                'answer_type': answer['answertype'],
                'question_id': answer['questionID'],
                'question_title': question['title'],
                'description': user['description'],
                'group': get_group(user['usergroup']),
                'tag': get_tags(answer['tags'])
            }
            return jsonify({'code': 1, 'msg': 'success', 'data': data})
        return jsonify({'code': -1, 'msg': 'unknown user'})
    return jsonify({'code': 0, 'msg': 'unknown answer'})


@app.route('/api/answer/get_answer_comment_list')
def get_answer_comment_list():
    """
    获取评论列表（倒序）
    :return:code(0=未知回答，1=成功)
    """
    answer_id = request.values.get('answer_id')
    db = Database()
    answer = db.get({'answerID': answer_id}, 'answers')
    if answer:
        comment_list = db.get({'answerID': answer_id}, 'answer_comments_info', 0)
        data = []
        for value in comment_list:
            user = db.get({'userID': value['userID']}, 'users')
            if user:
                data.append({
                    'user_id': value['userID'],
                    'user_nickname': user['nickname'],
                    'user_headportrait': user['headportrait'],
                    'content': value['content'],
                    'create_time': get_formative_datetime(value['createtime']),
                    'agree': value['agree'],
                    'usergroup': get_group(value['usergroup']),
                    'level': get_level(value['exp']),
                    'ID':value['acommentID'],
                })
        sorted(data, key=lambda a: a['agree'], reverse=True)
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unknown answer'})


@app.route('/api/answer/collect_answer')
def collect_answer():
    """
    关注某个回答
    :return: code:-1 = 回答不存在, -2 = 用户不存在, 0 = 关注失败, 1 = 关注成功
    """
    token = request.values.get('token')
    answer_id = request.values.get('answer_id')

    db = Database()
    user = db.get({'token': token}, 'users')
    answer = db.get({'answerID': answer_id}, 'answers')

    if not answer:
        return jsonify({'code': -1, 'msg': "the answer is not exist"})
    if not user:
        return jsonify({'code': -2, 'msg': "the user is not exist"})

    user_id = user['userID']
    success = db.insert({'userID': user_id, 'answerID': answer_id}, 'collectanswer')
    set_user_action(user_id, answer_id, 50)
    if success:
        set_exp(answer['userID'], 2, '回答被收藏')
        return jsonify({'code': 1, 'msg': "collect success"})
    else:
        return jsonify({'code': 0, 'msg': "there are something wrong when inserted the data into database"})


@app.route('/api/answer/un_collect_answer')
def un_collect_answer():
    """
    取消收藏
    :return:
    """
    token = request.values.get('token')
    answer_id = request.values.get('answer_id')

    db = Database()
    user = db.get({'token': token}, 'users')
    answer = db.get({'answerID': answer_id}, 'answers')

    if not answer:
        return jsonify({'code': -1, 'msg': "the answer is not exist"})
    if not user:
        return jsonify({'code': -2, 'msg': "the user is not exist"})

    user_id = user['userID']
    success = db.delete({'userID': user_id, 'answerID': answer_id}, 'collectanswer')
    if success:
        return jsonify({'code': 1, 'msg': "collect success"})
    else:
        return jsonify({'code': 0, 'msg': "there are something wrong when inserted the data into database"})


@app.route('/api/answer/get_collect_state')
def get_collect_answer_state():
    """
    获取是否已收藏
    :return:
    """
    token = request.values.get('token')
    answer_id = request.values.get('answer_id')

    db = Database()
    user = db.get({'token': token}, 'users')
    answer = db.get({'answerID': answer_id}, 'answers')

    if not answer:
        return jsonify({'code': -1, 'msg': "the answer is not exist"})
    if not user:
        return jsonify({'code': -2, 'msg': "the user is not exist"})

    user_id = user['userID']
    success = db.get({'userID': user_id, 'answerID': answer_id}, 'collectanswer')
    if success:
        return jsonify({'code': 1, 'msg': "collect success"})
    else:
        return jsonify({'code': 0, 'msg': "there are something wrong when inserted the data into database"})


@app.route('/api/answer/edit_answer')
def edit_answer():
    """
    编辑回答
    :return: code:0 = 编辑失败  1 = 编辑成功  -1 = 回答不存在
    """
    answer_id = request.values.get('answer_id')
    content = request.values.get('content')
    # 获取当前时间
    time_stamp = time.time()
    time_array = time.localtime(time_stamp)
    newtime = time.strftime("%Y--%m--%d %H:%M:%S", time_array)

    db = Database()
    answer = db.get({'answerID': answer_id}, 'answers')
    if not answer:
        return jsonify({'code': -1, 'msg': "the answer is not exist"})

    success = db.update({'answerID': answer_id}, {'content': content, 'edittime': newtime}, 'answers')
    if success:
        return jsonify({'code': 1, 'msg': "edit success"})
    else:
        return jsonify({'code': 0, 'msg': "there are something wrong when edited the data in database"})

@app.route('/api/answer/get_answer_comment_by_id')
def get_answer_comment_by_id():
    """
    获取回答评论
    :return: code(0=未知问题，1=成功)
    """
    comment_id = request.values.get('comment_id')
    db = Database()
    comment = db.get({'acommentID': comment_id}, 'answercomments')
    if comment:
        user = db.get({'userID':comment['userID']}, 'users')
        if user:
            return jsonify({'code': 1, 'msg': 'success', 'data': {'author': user, 'item': comment}})
        return jsonify({'code': 0, 'msg': 'user is not exist'})
    return jsonify({'code': -1, 'msg': 'comment is not exist'})

@app.route('/api/answer/add_answer_comment', methods=['POST'])
def add_answer_comment():
    """
    添加评论
    :return:code(0=未知用户，-1=未知回答，-2=无法添加评论，1=成功)
    """
    answer_id = request.form['answer_id']
    content = request.form['content']
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'answerID': answer_id}, 'answers')
        if answer:
            flag = db.insert({'userID': user['userID'], 'content': content, 'answerID': answer_id}, 'answercomments')
            if flag:
                set_exp(user['userID'], 2, '添加回答评论')
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -2, 'msg': 'unable to insert comment'})
        return jsonify({'code': -1, 'msg': 'unable to find answer'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/agree_answer')
def agree_answer():
    """
    对特定答案点赞
    :return: code(0=未知用户，-1=未知答案，-2=不能记录用户行为，-3=不能更新点赞数，1=成功)
    """
    answer_id = request.values.get('answer_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'answerID': answer_id}, 'answers')
        if answer:
            result = db.update({'answerID': answer_id}, {'agree': int(answer['agree']) + 1}, 'answers')
            flag = db.insert({'userID': user['userID'], 'targetID': answer_id, 'targettype': 1}, 'useraction')
            if result and flag:
                set_exp(answer['userID'], 1, '回答被点赞')
                return jsonify({'code': 1, 'msg': 'success'})
            if result:
                return jsonify({'code': -2, 'msg': 'unable to insert user action'})
            if flag:
                return jsonify({'code': -3, 'msg': 'unable to update agree number'})
        return jsonify({'code': -1, 'msg': 'unknown answer'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/un_agree_answer')
def un_agree_answer():
    """
    对特定答案取消点赞
    :return:
    """
    answer_id = request.values.get('answer_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'answerID': answer_id}, 'answers')
        if answer:
            result = db.update({'answerID': answer_id}, {'agree': int(answer['agree']) - 1}, 'answers')
            flag = db.delete({'userID': user['userID'], 'targetID': answer_id, 'targettype': 1}, 'useraction')
            if result and flag:
                return jsonify({'code': 1, 'msg': 'success'})
            if result:
                return jsonify({'code': -2, 'msg': 'unable to insert user action'})
            if flag:
                return jsonify({'code': -3, 'msg': 'unable to update agree number'})
        return jsonify({'code': -1, 'msg': 'unknown answer'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/get_answer_agree_state')
def get_answer_agree_state():
    """
    获取点赞点踩情况
    :return:
    """
    answer_id = request.values.get('answer_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        result = db.get({'userID': user['userID'], 'targetID': answer_id, 'targettype': 1}, 'useraction')
        if result:
            return jsonify({'code': 1, 'msg': 'success'})
        result = db.get({'userID': user['userID'], 'targetID': answer_id, 'targettype': 2}, 'useraction')
        if result:
            return jsonify({'code': 2, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'no record'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/agree_answer_comment')
def agree_answer_comment():
    """
    对特定评论点赞
    :return: code(0=未知用户，-1=未知评论，-2=不能记录用户行为，-3=不能更新点赞数，1=成功)
    """
    comment_id = request.values.get('comment_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'acommentID': comment_id}, 'answercomments')
        if answer:
            result = db.update({'acommentID': comment_id}, {'agree': int(answer['agree']) + 1}, 'answercomments')
            flag = db.insert({'userID': user['userID'], 'targetID': comment_id, 'targettype': 3}, 'useraction')
            if result and flag:
                return jsonify({'code': 1, 'msg': 'success'})
            if result:
                return jsonify({'code': -2, 'msg': 'unable to insert user action'})
            if flag:
                return jsonify({'code': -3, 'msg': 'unable to update agree number'})
        return jsonify({'code': -1, 'msg': 'unknown comment'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/agree_complain_comment')
def agree_complain_comment():
    """
    同意举报某一评论
    :return:
    """
    # 获取管理员token和评论ID
    token = request.headers.get('X-Token')
    id = request.values.get('id')

    db = Database()
    admin = db.get({'token': token, 'usergroup': 0}, 'users')
    if not admin:
        return jsonify({'code': 0, 'msg': 'the admin is not exist'})

    comment = db.get({'acommentID': id}, 'answercomments')
    if not comment:
        return jsonify({'code': -1, 'msg': 'the comment is not exist'})

    # 更新评论状态
    result = db.update({'acommentID': id}, {'state': -1}, 'answercomments')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/answer/disagree_complain_comment')
def disagree_complain_comment():
    """
    不同意举报某一评论
    :return:
    """
    # 获取管理员token和评论ID
    token = request.values.get('token')
    id = request.values.get('id')

    db = Database()
    admin = db.get({'token': token, 'usergroup': 0}, 'users')
    if not admin:
        return jsonify({'code': 0, 'msg': 'the admin is not exist'})

    comment = db.get({'acommentID': id}, 'answercomments')
    if not comment:
        return jsonify({'code': -1, 'msg': 'the comment is not exist'})

    # 更新评论状态
    result = db.update({'acommentID': id}, {'state': 0}, 'answercomments')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/answer/agree_complain_answer')
def agree_complain_answer():
    """
    同意举报某一回答
    :return:
    """
    # 获取管理员token和回答ID
    token = request.values.get('token')
    id = request.values.get('id')

    db = Database()
    admin = db.get({'token': token, 'usergroup': 0}, 'users')
    if not admin:
        return jsonify({'code': 0, 'msg': 'the admin is not exist'})

    comment = db.get({'answerID': id}, 'answers')
    if not comment:
        return jsonify({'code': -1, 'msg': 'the answer is not exist'})

    # 更新回答状态
    result = db.update({'answerID': id}, {'state': -1}, 'answers')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/answer/disagree_complain_answer')
def disagree_complain_answer():
    """
    不同意举报某一回答
    :return:
    """
    # 获取管理员token和回答ID
    token = request.values.get('token')
    id = request.values.get('id')

    db = Database()
    admin = db.get({'token': token, 'usergroup': 0}, 'users')
    if not admin:
        return jsonify({'code': 0, 'msg': 'the admin is not exist'})

    comment = db.get({'answerID': id}, 'answers')
    if not comment:
        return jsonify({'code': -1, 'msg': 'the answer is not exist'})

    # 更新评论状态
    result = db.update({'answerID': id}, {'state': 0}, 'answers')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/answer/disagree_answer')
def disagree_answer():
    """
        对特定答案点踩
        :return: code(0=未知用户，-1=未知答案，-2=不能记录用户行为，-3=不能更新点踩数，1=成功)
    """
    answer_id = request.values.get('answer_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'answerID': answer_id}, 'answers')
        if answer:
            plus = 1
            if get_level(user['exp']) >= 5:
                plus = 2
            result = db.update({'answerID': answer_id}, {'disagree': int(answer['disagree']) + plus}, 'answers')
            flag = db.insert({'userID': user['userID'], 'targetID': answer_id, 'targettype': 2}, 'useraction')
            if result and flag:
                return jsonify({'code': 1, 'msg': 'success'})
            if result:
                return jsonify({'code': -2, 'msg': 'unable to insert user action'})
            if flag:
                return jsonify({'code': -3, 'msg': 'unable to update agree number'})
        return jsonify({'code': -1, 'msg': 'unknown answer'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/un_disagree_answer')
def un_disagree_answer():
    """
        对特定答案取消点踩
        :return: code(0=未知用户，-1=未知答案，-2=不能记录用户行为，-3=不能更新点踩数，1=成功)
    """
    answer_id = request.values.get('answer_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answer = db.get({'answerID': answer_id}, 'answers')
        if answer:
            plus = 1
            if get_level(user['exp']) >= 5:
                plus = 2
            num = int(answer['disagree']) - plus
            if num < 0:
                num = 0
            result = db.update({'answerID': answer_id}, {'disagree': num}, 'answers')
            flag = db.delete({'userID': user['userID'], 'targetID': answer_id, 'targettype': 2}, 'useraction')
            if result and flag:
                return jsonify({'code': 1, 'msg': 'success'})
            if result:
                return jsonify({'code': -2, 'msg': 'unable to insert user action'})
            if flag:
                return jsonify({'code': -3, 'msg': 'unable to update agree number'})
        return jsonify({'code': -1, 'msg': 'unknown answer'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/back_get_answers')
def back_get_answers():
    """
    后台获取所有回答
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        answers = db.get({}, 'answersinfo', 0)
        wait = []
        deleted = []
        for value in answers:
            if value['state'] == 0:
                status = '正常'
            elif value['state'] == -1:
                status = '已清除'
            elif value['state'] == 1:
                status = '待审核'
            else:
                status = '其他'
            question = db.get({'questionID': value['questionID']}, 'questions')
            if question:
                value.update({'title': question['title']})
            else:
                value.update({'title': '未知问题'})
            value.update({'tags': get_tags(value['tags']), 'status': status,
                          'edittime': value['edittime'].strftime('%Y-%m-%d %H:%M:%S'),
                          'content': value['content'][:30] + '···'})
            if value['state'] == -1:
                deleted.append(value)
            elif value['status'] == 1:
                wait.append(value)
        return jsonify({'code': 1, 'msg': 'success', 'data': {'all': answers, 'wait': wait, 'deleted': deleted}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/delete_answer')
def delete_answer():
    """
    清除答案
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        answer_id = request.values.get('answer_id')
        flag = db.update({'answerID': answer_id}, {'state': -1}, 'answers')
        if flag:
            set_user_action(user['userID'], answer_id, 35)
            question = db.get({'questionID': flag['questionID']}, 'questions')
            if question:
                set_sys_message(user['userID'], 1, '您在 ' + question['title'] + ' 下的回答已被管理员清除！', flag['userID'], '回答清除')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/answer/complain_answer')
def complain_answer():
    """
    举报某个回答
    :return:
    """
    # 用户token和回答的ID
    token = request.values.get('token')
    answer_id = request.values.get('id')
    reason = request.values.get('reason')
    # 初始化数据库控制类
    db = Database()
    # 查询用户是否存在
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'the user is not exist'})
    # 查询回答是否存在
    answer = db.get({'answerID': answer_id}, 'answers')
    if not answer:
        return jsonify({'code': -1, 'msg': 'the answer is not exist'})
    # 更新回答状态
    result = db.update({'answerID': answer_id}, {'state': 1}, 'answers')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})
    # 记录用户行为
    db.insert({'userID': user['userID'], 'targetID': answer['answerID'], 'targettype': 6})
    # 插入举报记录
    db.insert({'reporter': user['userID'], 'itemID': answer_id, 'author': answer['userID'],'reason': reason, 'type':4})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/answer/get_user_answers')
def get_user_answers():
    """
    获取我的回答
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        questions = db.get({'userID': user['userID']}, 'answers', 0)
        for value in questions:
            value.update({
                'follow': db.count({'targetID': value['answerID'], 'targettype': 37}, 'useraction'),
                'comments': db.count({'answerID': value['answerID']}, 'answercomments')
            })
            question = db.get({'questionID': value['questionID']}, 'questions')
            if question:
                value.update({'title': question['title']})
            else:
                value.update({'title': '未知问题'})
        return jsonify({'code': 1, 'msg': 'success', 'data': questions})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    文章接口
"""


@app.route('/api/article/add_article', methods=['POST'])
def add_article():
    """
    新建文章
    :return: code:-1=用户不存在 0=新建失败  1=新建成功
    """
    token = request.form['token']
    content = request.form["content"]
    title = request.form['title']
    tags = request.form['tags']
    free = request.form['free']
    price = request.form['price']
    cover = request.form['cover']
    description = request.form['description']

    db = Database()

    user = db.get({'token': token}, 'users')
    if user:

        free_ = 1
        if free == 'true':
            free_ = 0
        flag = db.insert(
            {'content': content, 'userID': user['userID'], 'title': title, 'tags': tags, 'free': free_, 'price': price,
             'cover': cover, 'description': description},
            'article')
        if flag:
            set_exp(user['userID'], 10, '发布文章')
            return jsonify({'code': 1, 'msg': 'add success'})
        return jsonify({'code': 0, 'msg': 'there are something wrong when inserted the data into database'})
    return jsonify({'code': -1, 'msg': 'the user is not exist'})


@app.route('/api/article/edit_article', methods=['POST'])
def edit_article():
    """
    修改文章
    :return: code:-1=文章不存在 0=修改失败  1=修改成功
    """
    article_id = request.form["article_id"]
    content = request.form["content"]
    title = request.form['title']
    token = request.form['token']
    # 获取当前时间
    time_stamp = time.time()
    time_array = time.localtime(time_stamp)
    newtime = time.strftime("%Y--%m--%d %H:%M:%S", time_array)

    db = Database()
    article = db.get({'articleID': article_id}, 'article')
    user = db.get({'token': token}, 'users')
    if not article:
        return jsonify({'code': -1, 'msg': 'the article is not exist'})
    if not user:
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    if article['userID'] != user['userID'] and user['usergroup'] != 0:
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    success = db.update({'articleID': article_id}, {'content': content, 'edittime': newtime, 'title': title}, 'article')
    if success:
        return jsonify({'code': 1, 'msg': 'edit success'})
    else:
        return jsonify({'code': 0, 'msg': 'there are something wrong when inserted the data into database'})


@app.route('/api/article/collect_article')
def collect_article():
    """
    收藏一篇文章
    :return: code:0=收藏失败 1=收藏成功 -1=文章不存在 -2=用户不存在
    """
    article_id = request.values.get("article_id")
    token = request.values.get("token")

    db = Database()
    article = db.get({'articleID': article_id}, 'article')
    user = db.get({'token': token}, 'users')

    if not article:
        return jsonify({'code': -1, 'msg': 'the article is not exist'})
    if not user:
        return jsonify({'code': -2, 'msg': 'the user is not exist'})

    user_id = user['userID']
    success = db.insert({'userID': user_id, 'articleID': article_id}, 'collectarticle')
    if success:
        set_exp(article['userID'], 2, '文章被收藏')
        return jsonify({'code': 1, 'msg': 'collect success'})
    else:
        return jsonify({'code': 0, 'msg': 'there are something wrong when inserted the data into database'})


@app.route('/api/article/get_article_by_id')
def get_article_by_id():
    article_id = request.values.get('article_id')
    db = Database()
    article = db.get({'articleID': article_id}, 'article')
    if article:
        user = db.get({'userID': article['userID']}, 'users')
        if user:
            return jsonify({'code': 1, 'msg': 'success', 'data': {'author': user, 'item': article}})
        return jsonify({'code': 0, 'msg': 'user is not exist'})
    return jsonify({'code': -1, 'msg': 'comment is not exist'})


@app.route('/api/article/get_article_by userid')
def get_article_by_userid():
    user_id = request.values.get("user_id")
    db = Database()
    article = db.sql("select * from article where userID='%s'" % user_id)
    for val in article:
        if val['free'] == 0:
            val.update({
                'content': "付费内容"
            })

    return jsonify({'code': 1, 'msg': 'success', 'data': article})


@app.route('/api/article/un_collect_article')
def un_collect_article():
    """
    取消收藏文章
    :return:
    """
    article_id = request.values.get('article_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.delete({'userID': user['userID'], 'articleID': article_id}, 'collectarticle')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/get_article_collect_state')
def get_article_collect_state():
    """
    获取文章收藏状态
    :return:
    """
    article_id = request.values.get('article_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.get({'userID': user['userID'], 'articleID': article_id}, 'collectarticle')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'not collected'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/complain_article')
def complain_article():
    """
    举报某篇文章
    :return:
    """
    # 用户token和文章的ID
    token = request.values.get('token')
    article_id = request.values.get('id')
    reason = request.values.get('reason')
    # 初始化数据库控制类
    db = Database()
    # 查询用户是否存在
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'the user is not exist'})
    # 查询回答是否存在
    article = db.get({'articleID': article_id}, 'article')
    if not article:
        return jsonify({'code': -1, 'msg': 'the article is not exist'})
    # 更新回答状态
    result = db.update({'articleID': article_id}, {'state': 1}, 'article')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})
    # 记录用户行为
    db.insert({'userID': user['userID'], 'targetID': article['articleID'], 'targettype': 26})
    # 插入举报记录
    db.insert({'reporter': user['userID'], 'itemID': article_id, 'author': article['userID'],'reason': reason, 'type':6})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/article/agree_complain_article')
def agree_complain_article():
    """
    同意举报某一文章
    :return:
    """
    # 获取管理员token和评论ID
    token = request.values.get('token')
    id = request.values.get('id')

    db = Database()
    admin = db.get({'token': token, 'usergroup': 0}, 'users')
    if not admin:
        return jsonify({'code': 0, 'msg': 'the admin is not exist'})

    comment = db.get({'articleID': id}, 'article')
    if not comment:
        return jsonify({'code': -1, 'msg': 'the article is not exist'})

    # 更新评论状态
    result = db.update({'articleID': id}, {'state': -1}, 'article')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/article/disagree_complain_article')
def disagree_complain_article():
    """
    不同意举报某一评论
    :return:
    """
    # 获取管理员token和评论ID
    token = request.values.get('token')
    id = request.values.get('id')

    db = Database()
    admin = db.get({'token': token, 'usergroup': 0}, 'users')
    if not admin:
        return jsonify({'code': 0, 'msg': 'the admin is not exist'})

    comment = db.get({'articleID': id}, 'article')
    if not comment:
        return jsonify({'code': -1, 'msg': 'the comment is not exist'})

    # 更新评论状态
    result = db.update({'articleID': id}, {'state': 0}, 'article')
    if not result:
        return jsonify({'code': -2, 'msg': 'error when update the data'})

    return jsonify({'code': 1, 'msg': 'success'})


@app.route('/api/article/back_get_articles')
def back_get_articles():
    """
    后台获取article列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        normal_article = db.get({'state': 0}, 'articleinfo', 0)
        checking_article = db.get({'state': 1}, 'articleinfo', 0)
        for value in normal_article:
            value.update({'tags': get_tags(value['tags'])})
        for value in checking_article:
            value.update({'tags': get_tags(value['tags'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': {'normal': normal_article, 'checking': checking_article}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/delete_article')
def delete_article():
    """
    清除文章
    :return:
    """
    token = request.values.get('token')
    article_id = request.values.get('article_id')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        article = db.update({'articleID': article_id}, {'state': -1}, 'article')
        if article:
            set_user_action(user['userID'], article_id, 36)
            set_sys_message(user['userID'], 1, '您发布的文章 ' + article['title'] + ' 已被管理员清除！', article['userID'], '文章清除')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/get_article_allowed_group')
def get_article_allowed_group():
    """
    确认用户是否有文章编辑权限
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        if user['usergroup'] in ARTICLE_ALLOWED_GROUP:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'not allowed'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/get_user_articles')
def get_user_articles():
    """
    获取我的文章
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        articles = db.get({'userID': user['userID']}, 'article', 0)
        for value in articles:
            value.update({
                'follow': db.count({'articleID': value['articleID']}, 'collectarticle')
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': articles})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/get_tag_articles')
def get_tag_articles():
    """
    获取特定tag下的文章
    :return:
    """
    tag_id = request.values.get('tag_id')
    db = Database()
    articles = db.get({'state': 0}, 'articleinfo', 0)
    data = []
    for value in articles:
        tags = value['tags'].split(',')
        if tag_id in tags:
            value.update({'tags': get_tags(value['tags'])})
            data.append(value)
    return jsonify({'code': 1, 'msg': 'success', 'data': data})


@app.route('/api/article/get_article_info')
def get_article_info():
    """
    获取文章信息
    :return:
    """
    article_id = request.values.get('article_id')
    db = Database()
    article = db.get({'articleID': article_id}, 'articleinfo')
    if article:
        data = {
            'id': article['articleID'],
            'title': article['title'],
            'nickname': article['nickname'],
            'exp': article['exp'],
            'level': get_level(article['exp']),
            'group': get_group(article['usergroup']),
            'head_portrait': article['headportrait'],
            'cover': article['cover'],
            'description': article['description'],
            'tags': get_tags(article['tags']),
            'article_description': article['article_description'],
            'collect': db.count({'articleID': article['articleID']}, 'collectarticle'),
            'read': db.count({'targettype': 21, 'targetID': article['articleID']}, 'useraction'),
            'price': article['price'],
            'free': article['free'],
            'rate': get_article_rate(article_id),
            'user_id': article['userID']
        }
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unknown article'})


def get_article_rate(article_id):
    """
    获取文章评分
    :param article_id:
    :return:
    """
    db = Database()
    article = db.get({'articleID': article_id}, 'articleinfo')
    if db.count({'targettype': 23, 'targetID': article['articleID']}, 'useraction') + db.count(
            {'targettype': 24, 'targetID': article['articleID']}, 'useraction') > 0:
        rate = 2.5 + (db.count({'targettype': 23, 'targetID': article['articleID']}, 'useraction') - db.count(
            {'targettype': 24, 'targetID': article['articleID']}, 'useraction')) // (
                       db.count({'targettype': 23, 'targetID': article['articleID']}, 'useraction') + db.count(
                   {'targettype': 24, 'targetID': article['articleID']}, 'useraction')) * 2.5
        if rate < 0:
            rate = 0
        elif rate > 5:
            rate = 5
        return rate
    return 2.5


@app.route('/api/article/get_article_comment')
def get_article_comment():
    """
    获取文章的评论
    :return:
    """
    article_id = request.values.get('article_id')
    db = Database()
    comment = db.get({'articleID': article_id}, 'article_comments_info', 0)
    for value in comment:
        value.update({'group': get_group(value['usergroup']), 'level': get_level(value['exp']),
                      'ID':value['article_comment_id']})
    return jsonify({'code': 1, 'msg': 'success', 'data': comment})


@app.route('/api/article/get_article_comment_by_id')
def get_article_comment_by_id():
    """
    获取问题评论
    :return: code(0=未知问题，1=成功)
    """
    comment_id = request.values.get('comment_id')
    db = Database()
    comment = db.get({'article_comment_id': comment_id}, 'article_comments')
    if comment:
        user = db.get({'userID':comment['userID']}, 'users')
        if user:
            return jsonify({'code': 1, 'msg': 'success', 'data': {'author': user, 'item': comment}})
        return jsonify({'code': 0, 'msg': 'user is not exist'})
    return jsonify({'code': -1, 'msg': 'comment is not exist'})


@app.route('/api/article/add_article_comment', methods=['POST'])
def add_article_comment():
    """
    添加文章评论
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        content = request.form['content']
        article_id = request.form['article_id']
        flag = db.insert({'articleID': article_id, 'content': content, 'userID': user['userID']}, 'article_comments')
        set_user_action(user['userID'], article_id, 25)
        if flag:
            set_exp(user['userID'], 2, '发布文章评论')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/pay_article')
def pay_article():
    """
    为特定文章付费
    :return:
    """
    article_id = request.values.get('article_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        article = db.get({'articleID': article_id}, 'article')
        if article:
            if article['free'] == 0:
                pay = db.get({'from': user['userID'], 'receive': article['articleID'], 'type': 4}, 'pay_log')
                if not pay:
                    flag = change_account_balance(-float(article['price']), token)
                    if flag == 1:
                        flag = db.insert({'from': user['userID'], 'receive': article['articleID'], 'type': 4,
                                          'amount': -float(article['price'])},
                                         'pay_log')
                        flag1 = db.insert({'from': article['userID'], 'receive': article['articleID'], 'type': 5,
                                           'amount': float(article['price']) * 0.8}, 'pay_log')
                        author = db.get({'userID': article['userID']}, 'users')
                        if author:
                            change_account_balance(float(article['price']) * 0.8, author['token'])
                        if flag and flag1:
                            set_exp(user['userID'], 4, '阅读付费文章')
                            return jsonify({'code': 1, 'msg': 'success'})
                        change_account_balance(float(article['price']), token)
                        return jsonify({'code': -1, 'msg': 'unable to pay'})
                    elif flag == -1:
                        return jsonify({'code': -2, 'msg': 'not enough money'})
                    return jsonify({'code': -1, 'msg': 'unable to pay'})
                return jsonify({'code': 2, 'msg': 'already paid'})
            return jsonify({'code': 2, 'msg': 'free article'})
        return jsonify({'code': -3, 'msg': 'unknown article'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/get_paid')
def get_paid():
    """
    获取是否付费
    :return:
    """
    article_id = request.values.get('article_id')
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        pay = db.get({'from': user['userID'], 'receive': article_id, 'type': 4}, 'pay_log')
        if pay:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'not paid'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/get_article')
def get_article():
    """
    获取文章详细信息
    :return:
    """
    token = request.values.get('token')
    article_id = request.values.get('article_id')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        article = db.get({'articleID': article_id}, 'articleinfo')
        if article:
            if article['free'] != 1:
                pay = db.get({'from': user['userID'], 'receive': article_id, 'type': 4}, 'pay_log')
                if not pay:
                    return jsonify({'code': -1, 'msg': 'you have not paid'})
            data = {
                'title': article['title'],
                'nickname': article['nickname'],
                'user_id': article['userID'],
                'article_id': article['articleID'],
                'content': article['content'],
                'head_portrait': article['headportrait'],
                'edit_time': article['edittime'].strftime('%Y-%m-%d %H:%M:%S'),
                'description': article['description'],
                'cover': article['cover']
            }
            return jsonify({'code': 1, 'msg': 'success', 'data': data})
        return jsonify({'code': -2, 'msg': 'unknow article'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/article/pass_article')
def pass_article():
    id = request.values.get('id')
    result = article_state_change(0, id)
    if result:
        return jsonify({'code': 1, 'msg': "success"})

    return jsonify({'code': 0, 'msg': "fail"})


@app.route('/api/article/unpass_article')
def unpass_article():
    id = request.values.get('id')
    result = article_state_change(-1, id)
    if result:
        return jsonify({'code': 1, 'msg': "success"})

    return jsonify({'code': 0, 'msg': "fail"})


def article_state_change(state, id):
    db = Database()
    result = db.update({'articleID': id}, {'state': state}, 'article')
    return result


"""
    首页接口
"""


@app.route('/api/homepage/get_recommend', methods=['GET'])
def get_recommend():
    """
    根据用户推荐首页内容
    type=1 回答，0 提问，2 广告
    当前没有cf算法以后要改
    :return:code(-1=评分矩阵不存在 0=未知用户，1=成功)
    """
    # 用户token
    token = request.values.get('token')
    # 加载的次数
    pages = int(request.values.get('page'))
    # 每次加载量
    each_ = 6
    # 推荐的id列表
    recommend_question_ids = []
    # 流加载结果容器
    result = []
    # 获取用户信息
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        # 假装有广告,直接插入广告
        data = [{'title': '震惊！这样可以测出你的血脂', 'type': 2}]
        # 获取该用户最近的20条关于问题的行为
        the_question_action = db.sql("select * from useraction where userID = '%s' "
                                     "and targettype >=11 and targettype<=14 order by actiontime DESC limit 20" % user[
                                         'userID'])
        # 将最近一次行为的问题作为参考,进行item_cf推荐
        if the_question_action:
            target_question_id = the_question_action[0]['targetID']
            # 判断评分矩阵是否存在
            if not os.path.exists(CF_PATH + RATE_DIR + QUESTION_RATE_NAME):
                return jsonify({'code': -1, 'msg': 'the rate rectangle is not exist,please'
                                                   ' build it by function build_questoin_rate_rect'})
            # 获得相似度降序排列的问题序列
            recommend_question_ids = item_cf_api(QUESTION_SIMILAR_NAME, QUESTION_ID_NAME, target_question_id, 100)

        # 若无推荐内容，则根据日期获取最新的问题id列表
        if not recommend_question_ids:
            begin = (pages - 1) * each_ + 1
            end = pages * each_
            qs_id = db.sql("select questionID from questions order by edittime desc limit %d,%d" % (begin, end))
            for it in qs_id:
                result.append(it['questionID'])
        else:
            result = flow_loading(recommend_question_ids, each_, pages)

        # 录入结果
        for id in result:
            # 查询该id的问题信息
            out = db.sql("select * from questionsinfo where questionID = '%s'" % id)
            # 正则表达匹配图片
            pattern = re.compile(r'<[Ii][Mm][Gg].+?/?>')
            # 进行格式的处理
            for value1 in out:
                value1.update({
                    'type': 0,
                    'image': pattern.findall(value1['description']),
                    'follow': db.count({'targettype': 12, 'targetID': value1['questionID']}, 'useraction'),
                    'comment': db.count({'questionID': value1['questionID']}, 'questioncomments'),
                    'tags': get_tags(value1['tags'])
                })
                # 修改日期格式
                value1['edittime'] = get_formative_datetime(value1['edittime'])
                # 录入推荐的问题
                data.append(value1)

            # 查询该ID下的问题，取最多3条,按赞同数降序排列
            answers = db.sql("select * from answersinfo where questionID = '%s' order by agree DESC limit 3" % id)

            # 进行格式处理
            for value2 in answers:
                value2.update({'type': 1, 'image': pattern.findall(value2['content'])})
                # 修改日期格式
                value2['edittime'] = get_formative_datetime(value2['edittime'])
                # 录入推荐的回答
                data.append(value2)

        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/homepage/classify_by_tag')
def classify_by_tag():
    """
    获取特定类别的问题或者文章，type 1-问题+回答   2-文章
    :return:
    """
    # 需要获取的问题或文章tag
    tag = request.values.get('tag')
    type = int(request.values.get('type'))
    # 每次调用返回几个
    each = 6
    # 第几次调用(相当于第几页/第几次流加载），第一次为 1
    page = int(request.values.get('page'))

    db = Database()

    IDname = ""
    commentname = ""
    follow_type_number = 0

    begin = (page - 1) * each + 1
    end = page * each

    if type == 1:
        target = db.sql("select * from questions where tags like '%," + tag + ",%' or tags like '" + tag + ",%'"
                                                                                                           "or tags like '" + tag + "' or tags like '%," + tag + "' order by edittime desc limit %d,%d"
                        % (begin, end))
        IDname = "questionID"
        commentname = "questioncomments"
        follow_type_number = 12

    elif type == 2:
        target = db.sql("select * from article where tags like '%," + tag + ",%' or tags like '" + tag + ",%'"
                                                                                                         "or tags like '" + tag + "' or tags like '%," + tag + "' order by edittime desc limit %d,%d"
                        % (begin, end))
        IDname = "articleID"
        commentname = "article_comments"
        follow_type_number = 22

    for value in target:
        value.update({
            'tags': get_tags(value['tags']),
            'edittime': value['edittime'].strftime('%Y/%m/%d'),
            'follow': db.count({'targettype': follow_type_number, 'targetID': value[IDname]}, 'useraction'),
            'comment': db.count({IDname: value[IDname]}, commentname),
        })

    return jsonify({'code': 1, 'msg': 'success', 'data': target})


@app.route('/api/homepage/classify_all_tag')
def classify_all_tag():
    """
    获取所有类别的问题或者文章，type 1-问题+回答   2-文章
    :return:
    """
    # 需要获取的问题或文章tag
    type = int(request.values.get('type'))
    # 最终的数据
    data = []
    # 从数据库取出来的数据
    target = []
    # 流加载后的数据
    result = []
    db = Database()

    IDname = ""
    commentname = ""
    follow_type_number = 0

    category = db.sql("select * from tags where type=1")
    for cate in category:
        tag = str(cate['id'])
        if type == 1:
            target = db.sql("select * from questions where tags like '%," + tag + ",%' or tags like '" + tag + ",%'"
                                                                                                               "or tags like '" + tag + "' or tags like '%," + tag + "' order by edittime desc limit %d,%d"
                            % (1, 6))
            IDname = "questionID"
            commentname = "questioncomments"
            follow_type_number = 12
        elif type == 2:
            target = db.sql("select * from article where tags like '%," + tag + ",%' or tags like '" + tag + ",%'"
                                                                                                             "or tags like '" + tag + "' or tags like '%," + tag + "' order by edittime desc limit %d,%d"
                            % (1, 6))
            IDname = "articleID"
            commentname = "article_comments"
            follow_type_number = 22

        for value in target:
            value.update({
                'tags': get_tags(value['tags']),
                'edittime': value['edittime'].strftime('%Y/%m/%d'),
                'follow': db.count({'targettype': follow_type_number, 'targetID': value[IDname]}, 'useraction'),
                'comment': db.count({IDname: value[IDname]}, commentname),
            })

        result.append(target)

    return jsonify({'code': 1, 'msg': 'success', 'data': result})


def flow_loading(data, each, page, mode=0):
    """
    流加载

    :param data: 源数据
    :param each: 每次加载量
    :param page:第几次加载
    :return:本次需要加载的数据
    """
    # 转换成整数
    page = int(page)
    # 最多流加载几次
    max_page = int(len(data) / each) + 1
    # mode = 0时 超过最高加载次数的从第一次开始循环加载
    if (mode != 0):
        return []

    page = max_page if (page % max_page) == 0 else page % max_page

    begin_index = each * (page - 1)
    end_index = begin_index + each - 1

    if end_index >= len(data):
        end_index = len(data) - 1

    return data[begin_index:end_index + 1]


@app.route('/api/homepage/get_category')
def get_category():
    """
    获取分类(真的)
    :return:code(1=成功)
    """
    db = Database()
    tags = db.get({'type': 1}, 'tags', 0)
    data = []
    for value in tags:
        data.append({
            'name': value['name'],
            'id': value['id'],
            'page': 1
        })
    return jsonify({'code': 1, 'msg': 'success', 'data': data})


@app.route('/api/homepage/get_hot_search')
def get_hot_search():
    """
    获取热搜推荐
    :return:code(0=未知问题，1=成功)
    """
    db = Database()
    data = db.sql("select * from search_word order by time desc limit 10")
    for it in data:
        it.update({
            'close': False
        })

    return jsonify({'code': 1, 'msg': 'success', 'data': data})


@app.route('/api/homepage/get_history_search')
def get_history_search():
    """
    获取历史搜索
    :return:code(0=用户不存在，1=成功)
    """
    token = request.values.get("token")
    db = Database()
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'user is not found'})

    data = db.sql(
        "select * from history_search where userID='%s' group by content order by time desc limit 10" % user['userID'])

    for it in data:
        it.update({
            'close': False,
        })

    return jsonify({'code': 1, 'msg': 'success', 'data': data})


"""
    信息接口
"""


@app.route('/api/message/get_message_list')
def get_message_list():
    """
    获取聊天列表
    :return: code(0=未知用户，-1=空聊天列表，1=成功)
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        receive = db.get({'receiver': user['userID']}, 'chat_box', 0)
        post = db.get({'poster': user['userID']}, 'chat_box', 0)
        data = []
        for value in receive + post:
            data.append({
                'user_id': value['receiver'] if value['poster'] == user['userID'] else value['poster'],
                'nickname': value['receiver_nickname'] if value['poster'] == user['userID'] else value[
                    'poster_nickname'],
                'headportrait': value['receiver_headportrait'] if value['poster'] == user['userID'] else value[
                    'poster_headportrait'],
                'post_time': get_formative_datetime(value['post_time']),
                'content': value['content']
            })
        sorted(data, key=lambda a: a['post_time'], reverse=True)
        back = []
        for value in data:
            flag = True
            for value1 in back:
                if value1['user_id'] == value['user_id']:
                    flag = False
            if flag:
                back.append(value)
        return jsonify({'code': 1, 'msg': 'success', 'data': back})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/get_back_message_list')
def get_back_message_list():
    """
    获取聊天列表
    :return: code(0=未知用户，-1=空聊天列表，1=成功)
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        receive = db.get({'receiver': 0}, 'chat_box', 0)
        post = db.get({'poster': 0}, 'chat_box', 0)
        data = []
        for value in receive + post:
            data.append({
                'user_id': value['receiver'] if value['poster'] == 0 else value['poster'],
                'nickname': value['receiver_nickname'] if value['poster'] == 0 else value[
                    'poster_nickname'],
                'headportrait': value['receiver_headportrait'] if value['poster'] == 0 else value[
                    'poster_headportrait'],
                'post_time': get_formative_datetime(value['post_time']),
                'content': value['content']
            })
        sorted(data, key=lambda a: a['post_time'], reverse=True)
        back = []
        for value in data:
            flag = True
            for value1 in back:
                if value1['user_id'] == value['user_id']:
                    flag = False
            if flag:
                back.append(value)
        return jsonify({'code': 1, 'msg': 'success', 'data': back})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/add_message', methods=['POST'])
def add_message():
    """
    添加信息
    :return: code(0=未知用户，-1=无法录入，1=成功)
    """
    token = request.form['token']
    receiver = request.form['receiver']
    content = request.form['content']
    message_type = request.form['message_type']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.insert(
            {'receiver': receiver, 'content': content,
             'type': message_type, 'poster': user['userID']},
            'messages')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/get_chat_box')
def get_chat_box():
    """
    获取聊天室内容
    :return:code(0=未知用户，1=成功)
    """
    token = request.values.get('token')
    user_id = request.values.get('user_id')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        message1 = db.get({'poster': user['userID'], 'receiver': user_id}, 'messages', 0)
        message2 = db.get({'receiver': user['userID'], 'poster': user_id}, 'messages', 0)
        if message2 and message1:
            data = message1 + message2
        elif message1:
            data = message1
        elif message2:
            data = message2
        else:
            data = []
        data = sorted(data, key=lambda a: a['post_time'])
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/get_back_chat_box')
def get_back_chat_box():
    """
    获取聊天室内容
    :return:code(0=未知用户，1=成功)
    """
    token = request.headers.get('X-Token')
    user_id = request.values.get('user_id')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        message1 = db.get({'poster': 0, 'receiver': user_id}, 'messages', 0)
        message2 = db.get({'receiver': 0, 'poster': user_id}, 'messages', 0)
        if message2 and message1:
            data = message1 + message2
        elif message1:
            data = message1
        elif message2:
            data = message2
        else:
            data = []
        data = sorted(data, key=lambda a: a['post_time'])
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/back_add_message', methods=['POST'])
def back_add_message():
    """
    后台客服回复
    :return:
    """
    token = request.headers.get('X-Token')
    receiver = request.form['receiver']
    content = request.form['content']
    message_type = request.form['message_type']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.insert(
            {'receiver': receiver, 'content': content,
             'type': message_type, 'poster': 0},
            'messages')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/get_friend_list')
def get_friend_list():
    """
    获取好友列表
    :return: code(0=未知用户，1=成功)
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')  # 从token获取用户
    if user:
        # 根据token获取该用户的好友列表
        friend = db.sql(
            "select A.userID as user_id ,A.description as description,A.nickname as nickname,A.headportrait as "
            "headportrait,A.usergroup as "
            "usergroup,A.exp as exp from users A,(select C.* from followuser C,users D where C.userID = D.userID and "
            "D.token= '%s') B,followuser C where A.userID=C.userID and (C.target = B.userID) and C.userID = B.target "
            "" % token)
        for value in friend:
            value.update({'group': get_group(value['usergroup'])})
        if friend:
            return jsonify({'code': 1, 'msg': 'success', 'data': friend})
        return jsonify({'code': 1, 'msg': 'success', 'data': []})
    return jsonify({'code': 0, 'msg': 'unexpected user'})

    # user = db.get({'token': token}, 'users')  # 从token获取用户
    # if user:
    #     followed = db.get({'userID': user['userID']}, 'followuser', 0)  # 获取所有用户关注的用户
    #     data = []
    #     for value in followed:
    #         if db.get({'userID': value['target'], 'target': value['userID']}, 'followuser'):  # 判断关注的用户是否为互关，互关即好友
    #             friend = db.get({'userID': value['target']}, 'users')  # 获取好友信息
    #             if friend:
    #                 data.append({
    #                     'user_id': friend['userID'],
    #                     'nickname': friend['nickname'],
    #                     'headportrait': friend['headportrait'],
    #                     'usergroup': friend['usergroup'],
    #                     'exp': friend['exp']
    #                 })  # 存入信息
    #     return jsonify({'code': 1, 'msg': 'success', 'data': data})
    # return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/get_agree_list')
def get_agree_list():
    """
    获取点赞列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        """
            获取所有的用户行为
        """
        comment1 = db.get({'userID': user['userID']}, 'answercomments', 0)
        user_action = []
        for value in comment1:
            action = db.get({'targettype': 3, 'targetID': value['acommentID']}, 'useraction', 0)
            if action:
                user_action = user_action + action
        comment2 = db.get({'userID': user['userID']}, 'questioncomments', 0)
        for value in comment2:
            action = db.get({'targettype': 5, 'targetID': value['qcommentID']}, 'useraction', 0)
            if action:
                user_action = user_action + action
        answer = db.get({'userID': user['userID']}, 'answers', 0)
        for value in answer:
            action1 = db.get({'targettype': 1, 'targetID': value['answerID']}, 'useraction', 0)
            action2 = db.get({'targettype': 2, 'targetID': value['answerID']}, 'useraction', 0)
            if action1:
                user_action = user_action + action1
            if action2:
                user_action = user_action + action2
        """
            处理用户行为n
        """
        data = []
        for value in user_action:
            if value['targettype'] == 1 or value['targettype'] == 2:
                action = db.get({'actionID': value['actionID']}, 'agree_answer_info')
                if action:
                    data.append({
                        'type': value['targettype'],
                        'nickname': action['nickname'],
                        'userID': action['userID'],
                        'answerID': action['targetID'],
                        'title': action['title'],
                        'time': action['actiontime']
                    })
            elif value['targettype'] == 3:
                action = db.get({'actionID': value['actionID']}, 'agree_answer_comment_info')
                if action:
                    data.append({
                        'type': value['targettype'],
                        'nickname': action['nickname'],
                        'userID': action['userID'],
                        'commentID': action['targetID'],
                        'title': action['title'],
                        'time': action['actiontime']
                    })
            elif value['targettype'] == 5:
                action = db.get({'actionID': value['actionID']}, 'agree_question_comment_info')
                if action:
                    data.append({
                        'type': value['targettype'],
                        'nickname': action['nickname'],
                        'userID': action['userID'],
                        'commentID': action['targetID'],
                        'title': action['title'],
                        'time': action['actiontime']
                    })
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/get_at_list')
def get_at_list():
    """
    获取@列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        data = []
        q_at = db.like({'description': '@' + user['nickname'] + ' '}, 'q_at_info')
        for value in q_at:
            data.append({
                'nickname': value['nickname'],
                'time': value['edittime'],
                'id': value['questionID'],
                'type': 1,
                'headportrait': value['headportrait'],
                'title': value['title'],
                'user_id': value['userID'],
                'content': value['description']
            })
        qc_at = db.like({'content': '@' + user['nickname'] + ' '}, 'qc_at_info')
        for value in qc_at:
            data.append({
                'nickname': value['nickname'],
                'time': value['createtime'],
                'id': value['qcommentID'],
                'type': 2,
                'headportrait': value['headportrait'],
                'user_id': value['userID'],
                'content': value['content']
            })
        a_at = db.like({'content': '@' + user['nickname'] + ' '}, 'a_at_info')
        for value in a_at:
            data.append({
                'nickname': value['nickname'],
                'time': value['edittime'],
                'id': value['answerID'],
                'type': 3,
                'headportrait': value['headportrait'],
                'user_id': value['userID'],
                'content': value['content']
            })
        ac_at = db.like({'content': '@' + user['nickname'] + ' '}, 'ac_at_info')
        for value in ac_at:
            data.append({
                'nickname': value['nickname'],
                'time': value['createtime'],
                'id': value['acommentID'],
                'type': 3,
                'headportrait': value['headportrait'],
                'user_id': value['userID'],
                'content': value['content']
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


ALLOWED_USER_GROUP = {0, '0'}  # 允许发送广播用户组


@app.route('/api/message/add_sys_notice', methods=['POST'])
def add_sys_notice():
    """
    发送系统消息
    :return: code(0=未知用户，-1=权限不足，-2=无法添加，1=成功)
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        if user['usergroup'] in ALLOWED_USER_GROUP:
            content = request.form['content']
            message_type = request.form['type']
            target = request.form['target']
            name = request.form['name']
            flag = db.insert(
                {'content': content, 'type': message_type, 'userID': user['userID'], 'target': target, 'name': name},
                'sys_message')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -2, 'msg': 'unable to insert'})
        return jsonify({'code': -1, 'msg': 'permission denied'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


def set_sys_message(user_id, sys_type, content, target, name):
    """
    发送系统消息（内部接口）
    :param user_id: 用户id
    :param sys_type: 消息类型
    :param content: 内容
    :param target: 目标
    :return: boolean
    """
    db = Database()
    flag = db.insert({'userID': user_id, 'content': content, 'type': sys_type, 'target': target, 'name': name},
                     'sys_message')
    if flag:
        return True
    return False


@app.route('/api/message/get_sys_message')
def get_sys_message():
    """
    获取系统消息
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        all_message = db.get({'type': 0}, 'sys_message', 0)
        personal = db.get({'type': 1, 'target': user['userID']}, 'sys_message', 0)
        group = db.get({'type': 2, 'target': user['userID']}, 'sys_message', 0)
        demand = db.get({'type': 3, 'target': user['userID']}, 'sys_message', 0)

        data = {
            'all': all_message,
            'personal': personal,
            'group': group,
            'demand': demand,
        }
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/message/get_message')
def get_message():
    """
    获取某用户的私信
    :return: code:0=用户不存在 1=获取成功 -1=获取失败
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        message = db.get({'receiver', user['userID']}, 'messages')
        if message:
            return jsonify({'code': 1, 'msg': 'success', 'list': message})
        else:
            return jsonify({'code': -1, 'msg': 'fail'})
    else:
        return jsonify({'code': 0, 'msg': 'the user is not exist'})


@app.route('/api/message/get_comment_and_reply')
def get_comment_and_reply():
    """
    获取回复和评论
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        question = db.get({'userID': user['userID']}, 'questions', 0)
        q_data = []
        for value in question:
            comment = db.get({'questionID': value['questionID']}, 'question_comments_info', 0)
            q_data = q_data + comment
        answer = db.get({'userID': user['userID']}, 'answer_comment_info', 0)
        an_data = []
        for value in answer:
            comment = db.get({'answerID': value['answerID']}, 'answer_comments_info', 0)
            an_data = an_data + comment
        article = db.get({'userID': user['userID']}, 'article', 0)
        ar_data = []
        for value in article:
            comment = db.get({'articleID': value['articleID']}, 'article_comment_info', 0)
            ar_data = ar_data + comment
        return jsonify(
            {'code': 1, 'msg': 'success', 'data': {'question': q_data, 'answer': an_data, 'article': ar_data}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    上传接口
"""
ALLOWED_EXTENSIONS = ['png', 'jpg', 'JPG', 'PNG', 'gif', 'GIF']  # 允许上传的格式
ALLOWED_PIC = ['png', 'jpg', 'JPG', 'PNG']  # 允许上传的身份证格式


# 用于判断文件后缀
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


@app.route('/api/upload/upload_picture', methods=['POST'])
def upload_picture():
    """
    上传图片
    :return: code(0=失败，1=成功)
    """
    f = request.files['picture']
    if f and allowed_file(f.filename):
        basepath = os.path.dirname(__file__)  # 当前文件所在路径
        new_filename = str(int(time.time())) + secure_filename(f.filename)
        upload_path = os.path.join(basepath, 'static/uploads', new_filename)  # 注意：没有的文件夹一定要先创建，不然会提示没有该路径
        f.save(upload_path)
        return jsonify({'code': 1, 'msg': 'success', 'data': 'https://hanerx.tk:5000/static/uploads/' + new_filename})
    return jsonify({'code': 0, 'msg': 'unexpected type'})


def allowed_pic(filename):
    """
    检测文件是否符合要求
    :param filename:
    :return:
    """
    return '.' in filename and filename.rsplit('.', 1)[1] in ALLOWED_PIC


@app.route('/api/upload/upload_identity_card_back', methods=['POST'])
def upload_identity_card_back():
    """
    上传身份证反面
    :return:code(0=未知用户，-1=文件格式不正确-2=无法自动识别，1=成功）
    """
    back = request.files['back']
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        if back and allowed_pic(back.filename):
            basepath = os.path.dirname(__file__)  # 当前文件所在路径
            # 反面的图片
            back_filename = str(user['userID']) + '_back.' + back.filename.rsplit('.', 1)[1]
            upload_path_reverse = basepath+'/static/identity_card/'+back_filename  # 注意：没有的文件夹一定要先创建，不然会提示没有该路径
            back.save(upload_path_reverse)

            # 调用ocr进行反面识别文字信息(反面是有个人信息的那一面)
            info_reverse = identify(upload_path_reverse,show_process=True)

            flag = db.update({'userID': user['userID']}, {
                'back_pic': '/static/identity_card/' + back_filename},
                             'users')
            if flag:
                return jsonify({'code': 1, 'msg': 'success', 'data': info_reverse})
            return jsonify({'code': -2, 'msg': 'unable to identify'})
        return jsonify({'code': -1, 'msg': 'unexpected file'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/upload/upload_identity_card_front', methods=['POST'])
def upload_identity_card_front():
    """
    上传身份证正面
    :return:code(0=未知用户，-1=文件格式不正确-2=无法自动识别，1=成功）
    """
    front = request.files['front']
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        if front and allowed_pic(front.filename):
            basepath = os.path.dirname(__file__)  # 当前文件所在路径
            # 正面的图片
            front_filename = str(user['userID']) + '_front.' + front.filename.rsplit('.', 1)[1]
            upload_path = os.path.join(basepath, 'static/identity_card', front_filename)  # 注意：没有的文件夹一定要先创建，不然会提示没有该路径
            front.save(upload_path)

            flag = db.update({'userID': user['userID']}, {'front_pic': '/static/identity_card/' + front_filename, },
                             'users')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -2, 'msg': 'unable to identify'})
        return jsonify({'code': -1, 'msg': 'unexpected file'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    算法接口
"""


def item_cf_api(simi, id, target, num):
    """
    调用item_cf算法推荐
    :param simi: 相似度矩阵文件名(不包含路径)
    :param id:对象id列表文件名(不包含路径)
    :param target: 根据该ID进行相似推荐
    :param num: 推荐数量
    :return: ID序列
    """

    # 得到的推荐结果
    result = item_cf(SIMILAR_DIR + simi, SIMILAR_DIR + id, target, num)

    return result


@app.route('/api/algorithm/user_cf')
def user_cf_api(simi, id, target, num):
    """
    调用user_cf算法推荐问题
    :param simi: 相似度矩阵文件名(不包含路径)
    :param id:对象id列表文件名(不包含路径)
    :param target: 根据该ID进行相似推荐
    :param num: 推荐数量
    :return:
    """
    result = user_cf(SIMILAR_DIR + simi, SIMILAR_DIR + id, target, num)

    return result


@app.route('/api/algorithm/build_article_rate_rect')
def build_article_rate_rect():
    """
    建立文章的评分矩阵
    :return: code:0=失败 1=成功
    """
    # 为文章建立评分矩阵，评分矩阵的某一行是
    # 所有用户对某一篇文章的行为进行权值计算后得到的一个向量,所有文章对应一个向量组合成矩阵
    # 重置文件内容
    with open(CF_PATH + RATE_DIR + ARTICLE_RATE_NAME, "w") as f:
        pass
    db = Database()
    # targettype 对应的评分
    rate_dict = {21: 2, 22: 4, 23: 3, 24: -2, 25: 3}
    article = db.sql("select * from article")
    users = db.sql("select * from users order by userID ASC")

    for i in range(len(article)):
        # 对于第i篇文章的评分向量,没有参与的用户评分默认为1
        rates = {}
        for j in range(len(users)):
            rates[users[j]['userID']] = 1
            actions = db.sql(
                "select * from useraction where targetID='%s' and userID='%s' and targettype>=21 and targettype <=25 "
                "order by userID ASC" %
                (article[i]['articleID'], users[j]["userID"]))
            # 该用户对这篇文章的总评分
            rate = 0
            if actions:
                for k in range(len(actions)):
                    rt = rate_dict[actions[k]["targettype"]]
                    rate += rt
                rates[users[j]['userID']] = rate

        keys = rates.keys()
        with open(CF_PATH + RATE_DIR + ARTICLE_RATE_NAME, "a+") as f:
            f.write("ID:" + str(article[i]['articleID']) + " rate:")
            rate_str = ""
            for key in keys:
                rate_str += str(key) + ";" + str(rates[key]) + ";"
            rate_str = rate_str[:-1]
            f.write(rate_str + "\n")

    set_similarity_vec(CF_PATH + RATE_DIR, CF_PATH + SIMILAR_DIR, ARTICLE_RATE_NAME, ARTICLE_ID_NAME,
                       ARTICLE_SIMILAR_NAME)

    return jsonify({"code": 1})


@app.route('/api/algorithm/build_question_rate_rect')
def build_question_rate_rect():
    """
    建立问题的评分矩阵
    :return: code:0=失败 1=成功
    """
    # 为问题建立评分矩阵，评分矩阵的某一行是
    # 所有用户对某一个问题的行为进行权值计算后得到的一个向量,所有问题对应一个向量组合成矩阵

    # 重置文件内容
    with open(CF_PATH + RATE_DIR + QUESTION_RATE_NAME, "w") as f:
        pass
    db = Database()
    # targettype 对应的评分
    rate_dict = {11: 1.5, 12: 3, 13: 4, 14: 2}
    questions = db.sql("select * from questions")
    users = db.sql("select * from users order by userID ASC")

    for i in range(len(questions)):
        # 对于第i篇文章的评分向量,没有参与的用户评分默认为1
        rates = {}
        for j in range(len(users)):
            rates[users[j]['userID']] = 1
            actions = db.sql(
                "select * from useraction where targetID='%s' and userID='%s' and targettype>=11 and targettype <=14 "
                "order by userID ASC" %
                (questions[i]['questionID'], users[j]["userID"]))
            # 该用户对这篇文章的总评分
            rate = 0
            if actions:
                for k in range(len(actions)):
                    rt = rate_dict[actions[k]["targettype"]]
                    rate += rt
                rates[users[j]['userID']] = rate

        keys = rates.keys()
        with open(CF_PATH + RATE_DIR + QUESTION_RATE_NAME, "a+") as f:
            f.write("ID:" + str(questions[i]['questionID']) + " rate:")
            rate_str = ""
            for key in keys:
                rate_str += str(key) + ";" + str(rates[key]) + ";"
            rate_str = rate_str[:-1]
            f.write(rate_str + "\n")

    set_similarity_vec(CF_PATH + RATE_DIR, CF_PATH + SIMILAR_DIR, QUESTION_RATE_NAME, QUESTION_ID_NAME,
                       QUESTION_SIMILAR_NAME)

    return jsonify({"code": 1})


@app.route('/api/algorithm/build_user_rate_rect')
def build_user_rate_rect():
    """
    建立用户对问题的评分矩阵
    :return:
    """
    # 为用户建立评分矩阵，评分矩阵的某一行是
    # 用户对所有问题的行为进行权值计算后得到的一个向量,所有问题对应一个向量组合成矩阵
    # 重置文件内容
    with open(CF_PATH + RATE_DIR + USER_RATE_NAME, "w") as f:
        pass
    db = Database()
    # targettype 对应的评分
    rate_dict = {11: 1.5, 12: 3, 13: 4, 14: 2}
    questions = db.sql("select questionID from questions")
    users = db.sql("select userID from users order by userID ASC")
    for i in range(len(users)):
        rates = {}
        for j in range(len(questions)):
            # 对于第i个用户的评分向量,没有参与的问题评分默认为0
            rates[questions[j]['questionID']] = 0
            acts = db.sql("select targettype from useraction where userID='%s' and targetID='%s' "
                          "and targettype >= 11 and targettype <=15" % (users[i]['userID'], questions[j]['questionID']))
            rate = 0
            for k in range(len(acts)):
                rate += rate_dict[acts[k]['targettype']]
            rates[questions[j]['questionID']] = rate

        keys = rates.keys()
        with open(CF_PATH + RATE_DIR + USER_RATE_NAME, "a+") as f:
            f.write("ID:" + str(users[i]['userID']) + " rate:")
            rate_str = ""
            for key in keys:
                rate_str += str(key) + ";" + str(rates[key]) + ";"
            rate_str = rate_str[:-1]
            f.write(rate_str + "\n")

    set_similarity_vec(CF_PATH + RATE_DIR, CF_PATH + SIMILAR_DIR, USER_RATE_NAME, USER_ID_NAME, USER_SIMILAR_NAME)

    return jsonify({"code": 1})


@app.route('/api/algorithm/before_search')
def before_vague_search_api():
    """
    根据输入的内容模糊匹配待选搜索项
    例如：输入框内输入 王刚 ，则弹出 王刚，美食作家王刚，王**刚**等待选项，根据相似度和搜索热度排序
    用户便可以选择待选项进行搜索
    :return: code: 0-失败  1-成功
    """
    # 获取输入的内容
    input_word = request.values.get('word')
    db = Database()
    # 获取模糊匹配的热搜项
    word_bank = db.vague({"content": input_word}, "search_word")
    #  根据热搜项和输入内容的相似度进行排序，若相似度都小于等于0，则按照搜索热度排序
    # rank = select_by_similarity(input_word, word_bank)

    return jsonify({"code": 1, "msg": "success", "data": word_bank})


@app.route('/api/algorithm/search')
def vague_search_api():
    # 获取输入内容
    input_word = request.values.get('word')
    # 搜索什么内容  question-搜索问题  article-搜索文章 user-用户
    search_type = request.values.get('type')
    # 获取用户 token
    token = request.values.get('token')
    # 获取page数
    page = request.values.get('page')
    # 以下内容为根据当前搜索内容更新搜索表里面相印搜索项的热度

    # 获取该输入内容是否存在与热搜项
    db = Database()

    user = db.sql("select userID from users where token='%s'" % token)
    if user:
        history = db.sql("select * from history_search where userID='%s' and content='%s' order by time desc" % (
            user[0]['userID'], input_word))
        if history:
            now_time = time.localtime(time.time())
            now_time = time.strftime("%Y-%m-%d %H:%M:%S", now_time)
            db.sql("update history_search set time='%s' where userID='%s' and content='%s'" % (
                now_time, user[0]['userID'], input_word))
        else:
            db.sql("insert into history_search (userID,content) values ('%s','%s') " % (user[0]['userID'], input_word))

    word = db.get({'content': input_word}, 'search_word', 0)
    # 若存在，则搜索次数增加一次
    if word:
        db.update({'content': input_word}, {'time': word[0]['time'] + 1}, 'search_word')
    #  否则根据相似度进行处理
    else:
        # 获取所有热搜项
        word_bank = db.vague({"content": input_word}, "search_word")
        # 将输入内容和热搜项进行相似度计算，相似度低于0.5的不计入处理
        result = select_by_similarity(input_word, word_bank, 0.5)
        # 若存在相似度高于0.5的项，则认为输入项和该热搜项是完全相同的含义，可以视为热搜项的搜索次数+1
        if result:
            db.update({'content': result[0]['content']}, {'time': result[0]['time'] + 1}, 'search_word')
        # 否则认为该输入项为一个新的搜索项，加入搜索表中
        else:
            db.insert({'content': input_word}, 'search_word')

    # 以下为根据搜索项模糊搜索对应文章或问题
    data = []
    output = []
    # 根据搜索类型不同进行区分处理
    if search_type == "question":
        output = vg_search(0, input_word, page)
    elif search_type == "article":
        output = vg_search(1, input_word, page)
    elif search_type == "user":
        output = vg_search(2, input_word, page)
    else:
        output.append(vg_search(0, input_word, page))
        output.append(vg_search(1, input_word, page))
        output.append(vg_search(2, input_word, page))

    return jsonify({'code': 1, 'msg': 'success', 'data': output})


def vg_search(search_type, input_word, page):
    db = Database()
    output = []
    each_page = 6

    if search_type == 0:
        # 找到包含输入词语的问题
        data = db.sql("select * from questions where title like '%" + input_word + "%' order by edittime desc ")
        # 将问题题目和描述作为文本，输入词语作为关键词计算每一个问题的tfidf值
        for each in data:
            tfidf = tf_idf(input_word, each['title'] + ',' + each['description'])
            each.update(
                {'tags': get_tags(each['tags']), 'tfidf': tfidf, 'edittime': each['edittime'].strftime('%Y/%m/%d')})
            output.append(each)
    elif search_type == 1:
        # 找到包含输入词语的文章
        data = db.sql(
            "select * from article where title like '%" + input_word + "%' or content like '%" + input_word + "%'  order by edittime desc ")
        # 将文章内容作为文本，输入词语作为关键词计算每一篇文章的tfidf值
        for each in data:
            tfidf = tf_idf(input_word, each['content'])
            each.update(
                {'tags': get_tags(each['tags']), 'tfidf': tfidf, 'edittime': each['edittime'].strftime('%Y/%m/%d')})
            output.append(each)
    elif search_type == 2:
        data = db.like({'nickname': input_word}, 'users')
        for each in data:
            each.update({'tfidf': 0})
            output.append(each)

    # 按照tfidf值降序排列，值越高，文章或问题和输入词语关联越大
    output.sort(key=lambda it: it['tfidf'], reverse=True)

    output = flow_loading(output, each_page, page)
    return output


def tf_idf(word, content, type='question'):
    db = Database()
    # 计算tf值
    tf = compute_tf(word, content)
    total_item_number = 0
    contain_word_number = 0
    # 获取总问题数量或文章数量
    if type == 'question':
        total_item_number = db.count({}, 'questions')
    elif type == 'article':
        total_item_number = db.count({}, 'article')

    # 获取包含该词语的问题或文章数量
    if type == 'question':
        contain_word_number = db.count({'title': word, 'description': word}, 'questions') + 1
    elif type == 'article':
        contain_word_number = db.count({'title': word, 'content': word}, 'article') + 1

    # 计算idf值
    idf = math.log((total_item_number / contain_word_number) + 1)

    return tf * idf


"""
    专家接口
"""


@app.route('/api/specialist/get_my_answers')
def get_my_answers():
    """
    获取自己的回答
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        answers = db.get({'userID': user['userID']}, 'answersinfo', 0)
        for value in answers:
            value.update({'tags': get_tags(value['tags'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': answers})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/get_my_articles')
def get_my_articles():
    """
    获取自己的文章
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        articles = db.get({'userID': user['userID']}, 'articleinfo', 0)
        for value in articles:
            value.update({'tags': get_tags(value['tags'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': articles})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/get_my_fans')
def get_my_fans():
    """
    获取粉丝列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        followers = db.get({'target': user['userID']}, 'followinfo', 0)
        data = []
        for value in followers:
            data.append({
                'id': value['userID'],
                'nickname': value['follower_nickname'],
                'usergroup': get_group(value['follower_usergroup']),
                'exp': value['follower_exp'],
                'level': get_level(value['follower_exp']),
                'description': value['follower_description'],
                'head_portrait': value['follower_headportrait']
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/get_order_list')
def get_order_list():
    """
    获取付费咨询的预定列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        order = db.get({'target': user['userID']}, 'orderinfo', 0)
        order = sorted(order, key=lambda x: x['time'], reverse=True)
        for value in order:
            value.update({'level': get_level(value['exp']), 'usergroup': get_group(value['usergroup']),
                          'time': value['time'].strftime('%Y-%m-%d %H:%M:%S')})
        return jsonify({'code': 1, 'msg': 'success', 'data': order})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/confirm_order', methods=['POST'])
def confirm_order():
    """
    确认付费咨询预约
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        order_id = request.form['order_id']
        answer = request.form['answer']
        order = db.update_new({'orderID': order_id, 'target': user['userID']}, {'state': 1, 'answer': answer}, 'orders')
        flag = change_account_balance(float(order['price']), token)
        flag1 = db.insert(
            {'from': user['userID'], 'amount': float(order['price']), 'receive': order['orderID'], 'type': 6},
            'pay_log')
        if order and flag == 1 and flag1:
            set_sys_message(order['userID'], 3, '您向' + user['nickname'] + '提出的付费咨询已被回答！', order['userID'], '付费咨询被回答')
            set_exp(user['userID'], 4, '回答付费咨询')
            return jsonify({'code': 1, 'msg': 'success'})
        change_account_balance(-float(order['price']), token)
        return jsonify({'code': -1, 'msg': 'unable to find order or user is not correct'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/get_order')
def get_order():
    """
    获取咨询信息
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        order_id = request.values.get('order_id')
        order = db.get({'orderID': order_id}, 'orders_info')
        pattern = re.compile(r'<[Ii][Mm][Gg].+?/?>')
        if order and (order['userID'] == user['userID'] or order['target'] == user['userID']):
            order.update(
                {'user_user_group': get_group(order['user_user_group']), 'user_level': get_level(order['user_exp']),
                 'specialist_user_group': get_group(order['specialist_user_group']),
                 'specialist_level': get_level(order['specialist_exp']),
                 'image': pattern.findall(order['content']),
                 'time': order['time'].strftime('%Y-%m-%d %H:%M:%S')
                 })
            return jsonify({'code': 1, 'msg': 'success', 'data': order})


@app.route('/api/specialist/refuse_order')
def refuse_order():
    """
    拒绝付费咨询预约
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        order_id = request.values.get('order_id')
        order = db.update({'orderID': order_id, 'target': user['userID']}, {'state': -1}, 'orders')
        if order:
            user1 = db.get({'userID': order['userID']}, 'users')
            flag = change_account_balance(float(order['price']), user1['token'])
            flag1 = db.insert(
                {'from': user1['userID'], 'amount': float(order['price']), 'receive': order['orderID'], 'type': 7},
                'pay_log')
            if order and flag == 1 and flag1:
                set_sys_message(order['userID'], 3, '您向' + user['nickname'] + '提出的付费咨询已被拒绝！', order['userID'],
                                '付费咨询被拒绝')
                return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to find order or user is not correct'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/get_click_info')
def get_click_info():
    """
    获取点击量图表（还没想好怎么写）
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        article = db.get({'userID': user['userID']}, 'article', 0)
        article_read = 0
        agree = 0
        collect = 0
        for value in article:
            article_read += db.count({'targettype': 21, 'targetID': value['articleID']}, 'useraction')
            collect += db.count({'articleID': value['articleID']}, 'collectarticle')
        fan = db.count({'target': user['userID']}, 'followuser')
        answer = db.get({'userID': user['userID']}, 'answers', 0)
        answer_read = 0
        for value in answer:
            answer_read += db.count({'targettype': 11, 'targetID': value['answerID']}, 'useraction')
            collect += db.count({'answerID': value['answerID']}, 'collectanswer')
            agree += value['agree']
        pay = 0
        pay_log = db.get({'userID': user['userID']}, 'pay_log', 0)
        for value in pay_log:
            if value['amount'] > 0:
                pay += value['amount']
        return jsonify({'code': 1, 'msg': 'success',
                        'data': {'article_read': article_read, 'fan': fan, 'answer_read': answer_read, 'pay': pay,
                                 'collect': collect, 'agree': agree}})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/add_order', methods=['POST'])
def add_order():
    """
    添加付费咨询
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        target = request.form['target']
        price = request.form['price']
        content = request.form['content']
        flag = db.insert({'userID': user['userID'], 'target': target, 'price': price,
                          'content': content}, 'orders')
        flag1 = change_account_balance(-float(price), token)
        flag2 = db.insert(
            {'from': user['userID'], 'amount': -float(price), 'receive': target, 'type': 2},
            'pay_log')
        if flag and flag1 == 1 and flag2:
            set_sys_message(target, 3, '您有一份来自' + user['nickname'] + '咨询待回答！', target, '新付费咨询')
            set_exp(user['userID'], 4, '发布付费咨询')
            return jsonify({'code': 1, 'msg': 'success'})
        if flag1 == -1:
            return jsonify({'code': -2, 'msg': 'you do not have enough money'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/request_upgrade', methods=['POST'])
def request_upgrade():
    """
    请求升级用户组到专家
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        specialist_license = request.files['license']
        if specialist_license and allowed_pic(specialist_license.filename):
            basepath = os.path.dirname(__file__)  # 当前文件所在路径
            # 正面的图片
            filename = str(user['userID']) + '_license.' + specialist_license.filename.rsplit('.', 1)[1]
            upload_path = os.path.join(basepath, 'static/license', filename)  # 注意：没有的文件夹一定要先创建，不然会提示没有该路径
            specialist_license.save(upload_path)
            license_type = request.form['license_type']
            flag = db.update({'userID': user['userID']},
                             {'usergroup': 5, 'license_type': license_type,
                              'specialist_license': 'https://hanerx.tk:5000/static/license/' + filename}, 'users')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to request'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/specialist/get_historical_orders')
def get_historical_orders():
    """
    获取历史咨询
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        orders = db.get({'userID': user['userID']}, 'orders_info', 0)
        for order in orders:
            order.update(
                {'user_user_group': get_group(order['user_user_group']), 'user_level': get_level(order['user_exp']),
                 'specialist_user_group': get_group(order['specialist_user_group']),
                 'specialist_level': get_level(order['specialist_exp'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': orders})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    企业接口
"""


@app.route('/api/enterprise/add_demand', methods=['POST'])
def add_demand():
    """
    企业添加需求
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user and (user['usergroup'] == 3 or user['usergroup'] == 0):
        content = request.form['content']
        allowed_user = request.form['allowed_user']
        price = request.form['price']
        tags = request.form['tags']
        title = request.form['title']
        cover = request.form['cover']
        flag = db.insert(
            {'name': title, 'description': title + " 自动附属群", 'userID': user['userID'], 'head_portrait': cover},
            'groups')

        if flag:
            group = db.get({'userID': user['userID']}, 'groups', 0)
            db.insert({'groupID': group[len(group) - 1]['groupID'], 'userID': user['userID'], 'state': 0},
                      'group_members')
            flag = db.insert(
                {'userID': user['userID'], 'content': content, 'allowedUserGroup': allowed_user, 'price': price,
                 'title': title, 'cover': cover, 'group': group[len(group) - 1]['groupID'],
                 'tags': tags}, 'demands')
            if flag:
                set_exp(user['userID'], 12, '发布需求')
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -2, 'msg': 'unable to create group'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/get_my_demands')
def get_my_demands():
    """
    获取需求列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        demands = db.get({'userID': user['userID']}, 'demands_info', 0)
        for value in demands:
            value.update(
                {'tags': get_tags(value['tags']), 'createtime': value['createtime'].strftime('%Y-%m-%d %H:%M:%S')})
        return jsonify({'code': 1, 'msg': 'success', 'data': demands})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/get_signed_users')
def get_signed_users():
    """
    获取报名需求列表
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        demand_id = request.values.get('demand_id')
        signed_list = db.get({'target': demand_id}, 'signed_demand_info', 0)
        return jsonify({'code': 1, 'msg': 'success', 'data': signed_list})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/confirm_signed_user')
def confirm_signed_user():
    """
    确认报名的用户
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        user_id = request.values.get('user_id')
        target = request.values.get('target')
        flag = db.update({'userID': user_id, 'target': target}, {'state': 1}, 'sign_demand')
        demand = db.get({'demandID': target}, 'demands')
        db.insert({'userID': user_id, 'groupID': demand['group'], 'state': 2}, 'group_members')
        set_sys_message(user['userID'], 1, '您之前报名的' + demand['title'] + '已由企业审核通过，您现在是该需求的参与者了！', user_id, '报名信息')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to confirm'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/refuse_signed_user')
def refuse_signed_user():
    """
    拒绝报名的用户
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        user_id = request.values.get('user_id')
        target = request.values.get('target')
        flag = db.update({'userID': user_id, 'target': target}, {'state': -1}, 'sign_demand')
        demand = db.get({'demandID': target}, 'demands')
        set_sys_message(user['userID'], 1, '您之前报名的 ' + demand['title'] + ' 申请未通过！', user_id, '报名信息')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to refuse'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/un_refuse_signed_user')
def un_refuse_signed_user():
    """
    撤销拒绝报名的用户
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        user_id = request.values.get('user_id')
        target = request.values.get('target')
        flag = db.update({'userID': user_id, 'target': target}, {'state': 0}, 'sign_demand')
        demand = db.get({'demandID': target}, 'demands')
        set_sys_message(user['userID'], 1, '您之前报名的 ' + demand['title'] + ' 未通过申请被撤回！', user_id, '报名信息')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to refuse'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/close_demand')
def close_demand():
    """
    关闭需求
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        demand_id = request.values.get('demand_id')
        flag = db.update({'demandID': demand_id, 'userID': user['userID']}, {'state': 2}, 'demands')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to close or user is not correct'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/start_demand')
def start_demand():
    """
    开始项目停止招标
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        demand_id = request.values.get('demand_id')
        flag = db.update({'demandID': demand_id, 'userID': user['userID']}, {'state': 1}, 'demands')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to start or user is not correct'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/enterprise/request_enterprise_upgrade', methods=['POST'])
def request_enterprise_upgrade():
    """
    请求升级用户组到企业
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        specialist_license = request.files['license']
        if specialist_license and allowed_pic(specialist_license.filename):
            basepath = os.path.dirname(__file__)  # 当前文件所在路径
            # 正面的图片
            filename = str(user['userID']) + '_license.' + specialist_license.filename.rsplit('.', 1)[1]
            upload_path = os.path.join(basepath, 'static/license', filename)  # 注意：没有的文件夹一定要先创建，不然会提示没有该路径
            specialist_license.save(upload_path)
            license_type = request.form['license_type']
            flag = db.update({'userID': user['userID']},
                             {'usergroup': 6, 'license_type': license_type,
                              'specialist_license': 'https://hanerx.tk:5000/static/license/' + filename}, 'users')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to request'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    告示板接口
"""


@app.route('/api/board/sign_to_demand')
def sign_to_demand():
    """
    报名特定项目
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        demand_id = request.values.get('demand_id')
        demand = db.get({'demandID': demand_id}, 'demands')
        sign = db.get({'userID': user['userID'], 'target': demand_id}, 'sign_demand')
        if sign:
            return jsonify({'code': 2, 'msg': 'you are already signed'})
        if str(user['usergroup']) in demand['allowedUserGroup'].split(','):
            flag = db.insert({'userID': user['userID'], 'target': demand_id}, 'sign_demand')
            if flag:
                set_exp(user['userID'], 3, '报名参加需求')
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to sign'})
        return jsonify({'code': -2, 'msg': 'you are not allowed'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/get_sign_state')
def get_sign_state():
    """
    查看报名状态
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        demand_id = request.values.get('demand_id')
        flag = db.get({'userID': user['userID'], 'target': demand_id}, 'sign_demand')
        if flag:
            return jsonify({'code': 1, 'msg': 'success', 'data': flag})
        return jsonify({'code': -1, 'msg': 'not signed'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/get_board_recommend')
def get_board_recommend():
    """
    获取需求推荐
    :return:
    """
    token = request.values.get('token')
    page = request.values.get('page')
    each = 6

    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        userID = user['userID']
        # 推荐的相似用户个数
        num = 3
        # 每个用户推荐的问题数量
        q_num = 5

        questionID = []
        # 获取用户最可能感兴趣的问题id列表
        similar_user = user_cf_api(USER_SIMILAR_NAME, USER_ID_NAME, userID, 3)
        for key in similar_user.keys():
            rates = similar_user[key]
            count = 0
            for rate in rates:
                if ++count > q_num:
                    break
                question_id = ""
                for k in rate.keys():
                    question_id = k
                if question_id not in questionID:
                    questionID.append(question_id)
        tag_counter = {}
        total_counter = 0

        # 获取问题的类型并统计
        for i in range(len(questionID)):
            question = db.get({'questionID': questionID[i]}, 'questions')
            if not question:
                continue
            if not question['tags']:
                continue
            tags = question['tags'].split(',')
            total_counter += len(tags)
            for tag in tags:
                if tag in tag_counter.keys():
                    tag_counter[tag] += 1
                else:
                    tag_counter[tag] = 1

        # 得到用户的类型偏好比例
        like_rate = []
        for key in tag_counter.keys():
            tag_counter[key] = tag_counter[key] / total_counter
            like_rate.append({'id': key, 'val': float(tag_counter[key])})

        like_rate.sort(key=lambda x: x['val'], reverse=True)

        # 获取最偏好的前3个类别
        choosen_type = []
        for i in range(0, 3):
            if i >= len(like_rate):
                break
            choosen_type.append(like_rate[i]['id'])
        # 没有获取到偏好的情况
        if not choosen_type:
            tags = db.sql("select id from tags")
            tag_id = []
            for tag in tags:
                tag_id.append(str(tag['id']))
            while len(choosen_type) < 3:
                idx = random.randint(0, len(tag_id) - 1)
                if tags[idx]['id'] not in choosen_type:
                    choosen_type.append(str(tags[idx]['id']))

        demand = db.get({'state': 0}, 'demands_info', 0)
        result = []
        for value in demand:
            tags = value['tags']
            if not tags:
                continue
            tags = tags.split(',')
            # 求交集
            tmp = [val for val in tags if val in choosen_type]
            if tmp:
                value.update({
                    'tags': get_tags(value['tags']),
                    'usergroup': get_group(value['usergroup']),
                    'level': get_level(value['exp']),
                    'allowed_user_group': value['allowedUserGroup'].split(',')
                })
                if (str(user['usergroup']) in value['allowedUserGroup'].split(',')) and (value not in result):
                    result.append(value)

        result = flow_loading(result, each, page)

        return jsonify({'code': 1, 'msg': 'success', 'data': result})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/get_board_category')
def get_board_category():
    """
    获取告示板分类
    :return:
    """
    db = Database()
    tags = db.get({'type': 1}, 'tags', 0)
    data = []
    for value in tags:
        data.append({
            'name': value['name'],
            'id': value['id']
        })
    return jsonify({'code': 1, 'msg': 'success', 'data': data})


@app.route('/api/board/get_child_category')
def get_child_category():
    """
    获取父级标签下的子集标签
    :return:
    """
    db = Database()
    tag_id = request.values.get('tag_id')
    tags = db.get({'father': tag_id}, 'tags', 0)

    if not tags:
        return jsonify({'code': 0, 'msg': 'tag is not exist'})

    data = []
    for value in tags:
        data.append({
            'name': value['name'],
            'id': value['id']
        })
    return jsonify({'code': 1, 'msg': 'success', 'data': data})


@app.route('/api/board/get_demand')
def get_demand():
    """
    获取需求信息
    :return:
    """
    demand_id = request.values.get('demand_id')
    db = Database()
    demand = db.get({'demandID': demand_id}, 'demands_info')
    if demand:
        demand.update({
            'tags': get_tags(demand['tags']),
            'usergroup': get_group(demand['usergroup']),
            'level': get_level(demand['exp']),
            'read': db.count({'targettype': 52}, 'useraction'),
            'collect': db.count({'targettype': 53}, 'useraction')
        })
        return jsonify({'code': 1, 'msg': 'success', 'data': demand})
    return jsonify({'code': 0, 'msg': 'unknown demand'})


@app.route('/api/board/collect_demand')
def collect_demand():
    """
    收藏需求
    :return:
    """
    demand_id = request.values.get('demand_id')
    db = Database()
    token = request.values.get('token')
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.insert({'targettype': 53, 'userID': user['userID'], 'targetID': demand_id}, 'useraction')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/un_collect_demand')
def un_collect_demand():
    """
    取消需求收藏
    :return:
    """
    demand_id = request.values.get('demand_id')
    db = Database()
    token = request.values.get('token')
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.delete({'targettype': 53, 'userID': user['userID'], 'targetID': demand_id}, 'useraction')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/get_demand_collect_state')
def get_demand_collect_state():
    """
    获取需求收藏状态
    :return:
    """
    demand_id = request.values.get('demand_id')
    db = Database()
    token = request.values.get('token')
    user = db.get({'token': token}, 'users')
    if user:
        flag = db.get({'targettype': 53, 'userID': user['userID'], 'targetID': demand_id}, 'useraction')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/get_demands_by_tag')
def get_demands_by_tag():
    """
    获取该tag下的所有需求
    :return:
    """
    tag_id = request.values.get('tag_id')
    db = Database()
    demands = db.get({'state': 0}, 'demands_info', 0)
    data = []
    for value in demands:
        tags = get_tags(value['tags'])
        for tag in tags:
            if tag['id'] == tag_id:
                value.update({
                    'tags': get_tags(value['tags']),
                    'usergroup': get_group(value['usergroup']),
                    'level': get_level(value['exp']),
                })
                data.append(value)
                break
    return jsonify({'code': 1, 'msg': 'success', 'data': data})


@app.route('/api/board/back_get_demands')
def back_get_demands():
    """
    后台获取需求列表
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        demands = db.get({}, 'demands_info', 0)
        for value in demands:
            value.update({
                'tags': get_tags(value['tags']),
                'usergroup': get_group(value['usergroup']),
                'level': get_level(value['exp']),
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': demands})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/delete_demand')
def delete_demand():
    """
    清除需求
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        demand_id = request.values.get('demand_id')
        flag = db.update({'demandID': demand_id}, {'state': -1}, 'demands')
        if flag:
            set_user_action(user['userID'], demand_id, 33)
            set_sys_message(user['userID'], 1, '您发布的需求 ' + flag['title'] + ' 已被管理员清除！', flag['userID'], '需求清除')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/board/get_my_demand')
def get_my_demand():
    """
    获取我所有的需求
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        demands = db.get({'userID': user['userID']}, 'sign_demand', 0)
        data = []
        for value in demands:
            demand = db.get({'demandID': value['target']}, 'demands')
            if demand:
                demand.update({'tags': get_tags(demand['tags'])})
                data.append(demand)
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    学院接口
"""


@app.route('/api/school/get_free_article')
def get_free_article():
    """
    获取所有免费文章
    :return:code:0=没有文章  1=成功
    """
    db = Database()
    # 免费并且没有被清除的文章
    article = db.sql("select * from article where free=1 and state=0")
    if article:
        return jsonify({'code': 1, 'msg': 'success', 'data': article})
    return jsonify({'code': 0, 'msg': 'no article'})


@app.route('/api/school/get_charge_article')
def get_charge_article():
    """
    获取所有收费文章
    :return:code:0=没有文章  1=成功
    """
    db = Database()
    # 收费并且没有被清除的文章
    article = db.sql("select * from article where free=0 and state=0")
    if article:
        return jsonify({'code': 1, 'msg': 'success', 'data': article})
    return jsonify({'code': 0, 'msg': 'no article'})


@app.route('/api/school/get_user_article')
def get_user_article():
    """
    获取某个用户在学院内发表的文章
    :return:code:-1=用户不存在 0=没有文章  1=成功
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    # 若用户存在则继续处理
    if user:
        # 某个用户发表的，并且没有被清除的文章
        article = db.get({'userID': user['userID'], 'state': 0}, 'article')
        if article:
            return jsonify({'code': 1, 'msg': 'success', 'data': article})
        return jsonify({'code': 0, 'msg': 'no article'})
    return jsonify({'code': -1, 'msg': 'the user is not exist'})


@app.route('/api/school/get_article_by_tag')
def get_article_by_tag():
    """
    根据tag查找文章
    :return:code:0=没有符合条件的文章  1=成功
    """
    tag_id = request.values.get('tag_id')
    db = Database()
    # 先获取所有未清除的文章
    article = db.sql({'state': 0}, 'article')
    # 存放返回的数据
    data = []
    # 遍历所有文章
    for it in article:
        # 获取这篇文章的tag列表
        tags = get_tags(it['tags'])
        # 遍历并判断每一项tag是否符合搜索项
        for tg in tags:
            # 若符合，则加入返回容器中
            if tg == tag_id:
                it.update({'tags': tags})
                data.append(it)
                break
    if data:
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'no article'})


@app.route('/api/school/get_similar_article')
def get_similar_article():
    """
    根据某一篇文章进行相似文章推荐
    :return:
    """
    article_id = request.values.get('article_id')
    rate_dir = '/etc/project-agent/CF/rate_rect/article_rate_rect.txt'
    # 判断评分矩阵是否存在
    if not os.path.exists(rate_dir):
        return jsonify({'code': 0, 'msg': 'the rate rectangle is not exist,please'
                                          ' build it by function build_article_rate_rect'})
    # 推荐的文章id,最多3条，相似度降序排列
    recommend_article = item_cf_api("article_similar_rect.txt", "article_id_list.txt", article_id,
                                    3)

    return jsonify({'code': 1, 'msg': 'success', 'data': recommend_article})


@app.route('/api/school/get_recommend_article')
def get_recommend_article():
    """
    根据用户最近浏览的文章进行推荐
    :return:code:-1=评分矩阵未建立  0=用户不存在  1=成功
    """
    token = request.values.get('token')
    page = int(request.values.get('page'))
    each_page = 6
    # 推荐结果容器
    recommend_article = []
    # 流加载结果容器
    result = []
    db = Database()
    user = db.get({'token': token}, 'users')

    rate_dir = CF_PATH + RATE_DIR + ARTICLE_RATE_NAME

    if not user:
        return jsonify({'code': 0, 'msg': 'user is not exist'})
    # 判断评分矩阵是否存在
    if not os.path.exists(rate_dir):
        return jsonify({'code': -1, 'msg': 'the rate rectangle is not exist,please'
                                           ' build it by function build_article_rate_rect'})

    # 查找该用户最近浏览的最多10篇文章
    action = db.sql("select distinct targetID from useraction where userID='%s' and targettype >=21 and targettype<=25 "
                    "order by actiontime DESC limit 1" % user['userID'])

    # 推荐的文章id,最多3条，相似度降序排列
    for each in action:
        ids = item_cf_api(ARTICLE_SIMILAR_NAME, ARTICLE_ID_NAME, each['targetID'], 6)
        for id in ids:
            article = db.get({'articleID': id}, 'article')
            article.update({'tags': get_tags(article['tags'])})
            if article not in recommend_article:
                recommend_article.append(article)

    # 若推荐内容为空，则随机推荐
    if not recommend_article:
        begin = (page - 1) * each_page + 1
        end = page * each_page
        result = db.sql("select * from article order by edittime DESC limit %d,%d" % (begin, end))
        for value in result:
            value.update({'tags': get_tags(value['tags'])})
    else:
        result = flow_loading(recommend_article, each_page, page)

    return jsonify({'code': 1, 'msg': 'success', 'data': result})


"""
    群聊接口
"""


@app.route('/api/group/new_group', methods=['POST'])
def new_group():
    """
    新建群组
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        name = request.form['name']
        description = request.form['description']
        head_portrait = request.form['head_portrait']
        flag = db.insert(
            {'name': name, 'description': description, 'userID': user['userID'], 'head_portrait': head_portrait},
            'groups')

        if flag:
            group = db.get({'userID': user['userID']}, 'groups', 0)
            db.insert({'groupID': group[len(group) - 1]['groupID'], 'userID': user['userID'], 'state': 0},
                      'group_members')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to create'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/add_group_member')
def add_group_member():
    """
    添加组员
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        group_member1 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 0}, 'group_members')
        group_member2 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 1}, 'group_members')
        if group_member1 or group_member2:
            user_id = request.values.get('user_id')
            flag = db.insert({'userID': user_id, 'groupID': group_id, 'state': 3}, 'group_members')
            group = db.get({'groupID': group_id}, 'groups')
            if group:
                set_sys_message(user['userID'], 2, '您已被管理员邀请加入群聊 ' + group['name'] + ' ,请及时确认！', user_id, '群聊通知')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to add'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/confirm_invite')
def confirm_invite():
    """
    确认加入群组
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        flag = db.update({'groupID': group_id, 'userID': user['userID']}, {'state': 2}, 'group_members')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to confirm'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/set_admin')
def set_admin():
    """
    设置群管理员
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    group_id = request.values.get('group_id')
    if db.get({'userID': user['userID'], 'groupID': group_id}, 'groups'):
        user_id = request.values.get('user_id')
        member = db.get({'userID': user_id, 'groupID': group_id, 'state': 2}, 'group_members')
        if member:
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'state': 1}, 'group_members')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'database problems'})
        return jsonify({'code': -2, 'msg': 'unknown user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/set_normal')
def set_normal():
    """
    取消设置群管理员
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if not user:
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    group_id = request.values.get('group_id')
    if db.get({'userID': user['userID'], 'groupID': group_id}, 'groups'):
        user_id = request.values.get('user_id')
        member = db.get({'userID': user_id, 'groupID': group_id, 'state': 1}, 'group_members')
        if member:
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'state': 2}, 'group_members')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'database problems'})
        return jsonify({'code': -2, 'msg': 'unknown user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


def call_group_members(state, content, group_id):
    """
    呼叫所有成员
    :param state: 成员等级
    :param content: 内容
    :param group_id: 群号
    :return:
    """
    db = Database()
    group_members = db.get({'groupID': group_id, 'state': state}, 'group_members')
    for value in group_members:
        set_sys_message(0, 2, content, value['userID'], '群聊通知')


@app.route('/api/group/join_group')
def join_group():
    """
    加入群聊
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        flag = db.insert({'groupID': group_id, 'userID': user['userID'], 'state': 4}, 'group_members')
        if flag:
            group = db.get({'groupID': group_id}, 'groups')
            if group:
                call_group_members(0, '用户 ' + user['nickname'] + ' 申请加入 ' +
                                   group['name'] + ' 请尽快审核', group_id)
                call_group_members(1, '用户 ' + user['nickname'] + ' 申请加入 ' +
                                   group['name'] + ' 请尽快审核', group_id)
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to join'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/confirm_join')
def confirm_join():
    """
    同意加群申请
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        group_member1 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 0}, 'group_members')
        group_member2 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 1}, 'group_members')
        if group_member1 or group_member2:
            user_id = request.values.get('user_id')
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'state': 2}, 'group_members')
            group = db.get({'groupID': group_id}, 'groups')
            if group:
                set_sys_message(user['userID'], 2, '您加入的群聊 ' + group['name'] + ' 的申请已被管理员通过！', user_id, '群聊通知')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to add'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/refuse_join')
def refuse_join():
    """
    拒绝加群申请
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        group_member1 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 0}, 'group_members')
        group_member2 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 1}, 'group_members')
        if group_member1 or group_member2:
            user_id = request.values.get('user_id')
            flag = db.delete({'userID': user_id, 'groupID': group_id}, 'group_members')
            group = db.get({'groupID': group_id}, 'groups')
            if group:
                set_sys_message(user['userID'], 2, '您加入的群聊 ' + group['name'] + ' 的申请已被管理员拒绝！', user_id, '群聊通知')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to add'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/silent_user')
def silent_user():
    """
    禁言某个群员
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        group_member1 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 0}, 'group_members')
        group_member2 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 1}, 'group_members')
        if group_member1:
            user_id = request.values.get('user_id')
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'silent': 1}, 'group_members')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to add'})
        elif group_member2:
            user_id = request.values.get('user_id')
            group_member = db.get({'groupID': group_id, 'userID': user_id}, 'group_members')
            if group_member['state'] <= group_member2['state']:
                return jsonify({'code': 0, 'msg': 'unexpected user'})
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'silent': 1}, 'group_members')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to silent'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/un_silent_user')
def un_silent_user():
    """
    解除禁言某个群员
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        group_member1 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 0}, 'group_members')
        group_member2 = db.get({'groupID': group_id, 'userID': user['userID'], 'state': 1}, 'group_members')
        if group_member1:
            user_id = request.values.get('user_id')
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'silent': 0}, 'group_members')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to add'})
        elif group_member2:
            user_id = request.values.get('user_id')
            group_member = db.get({'groupID': group_id, 'userID': user_id}, 'group_members')
            if group_member['state'] <= group_member2['state']:
                return jsonify({'code': 0, 'msg': 'unexpected user'})
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'silent': 0}, 'group_members')
            if flag:
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to add'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/send_group_message', methods=['POST'])
def send_group_message():
    """
    发送消息
    :return:
    """
    token = request.form['token']
    db = Database()
    user = db.get({'token': token}, 'users')
    group_id = request.form['group_id']
    if not user:
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    member = db.sql(
        'SELECT * FROM group_members WHERE ( state= 0 OR state=1 OR state=2 ) AND userID = %s AND groupID = %s '
        'AND silent=0' % (user['userID'], group_id))
    if member:
        content = request.form['content']
        flag = db.insert({'userID': user['userID'], 'groupID': group_id, 'content': content}, 'group_message')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to send'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/get_group_message')
def get_group_message():
    """
    获取群聊消息
    :return:
    """
    token = request.values.get('token')
    db = Database()
    group_id = request.values.get('group_id')
    user = db.get({'token': token}, 'users')
    if db.get({'userID': user['userID'], 'groupID': group_id}, 'group_members'):
        if not db.get({'groupID': group_id, 'state': 0}, 'groups'):
            return jsonify({'code': -1, 'msg': 'group is not available'})
        message = db.get({'groupID': group_id}, 'group_message_info', 0)
        for value in message:
            value.update({'usergroup': get_group(value['usergroup']), 'level': get_level(value['exp'])})
        return jsonify({'code': 1, 'msg': 'success', 'data': message})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/get_groups')
def get_groups():
    """
    获取用户的所有群组
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        groups = db.get({'userID': user['userID'], 'group_state': 0}, 'group_members_info', 0)
        data = []
        for value in groups:
            message = db.get({'groupID': value['groupID']}, 'group_message_info', 0)
            last = {
                'nickname': '',
                'content': "",
                'time': ''
            }
            if message:
                last = message[len(message) - 1]
            data.append({
                'id': value['groupID'],
                'head_portrait': value['head_portrait'],
                'name': value['name'],
                'description': value['description'],
                'last_message': {
                    'nickname': last['nickname'],
                    'content': last['content'],
                    'time': last['time']
                }
            })
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/get_group_members')
def get_group_members():
    """
    获取当前群组的成员列表
    :return:
    """
    group_id = request.values.get('group_id')
    db = Database()
    members = db.get({'groupID': group_id}, 'group_members_info', 0)
    for value in members:
        value.update({
            'usergroup': get_group(value['usergroup']),
            'level': get_level(value['exp'])
        })
    return jsonify({'code': 1, 'msg': 'success', 'data': members})


@app.route('/api/group/ban_user')
def ban_user():
    """
    封禁用户
    :return:
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        member = db.get({'userID': user['userID'], 'groupID': group_id}, 'group_members')
        user_id = request.values.get('user_id')
        if member['state'] == 0:
            flag = db.update({'userID': user_id, 'groupID': group_id}, {'state': 5}, 'group_members')
            if flag:
                group = db.get({'groupID': group_id}, 'groups')
                if group:
                    set_sys_message(user['userID'], 2, '您已被管理员 ' + user['nickname'] + ' 踢出群组 ' + group['name'] + ' !',
                                    user_id, '群聊通知')
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to ban user'})
        elif member['state'] == 1:
            member1 = db.get({'userID': user_id, 'groupID': group_id}, 'group_members')
            if member1['state'] > member['state']:
                flag = db.update({'userID': user_id, 'groupID': group_id}, {'state': 5}, 'group_members')
                if flag:
                    group = db.get({'groupID': group_id}, 'groups')
                    if group:
                        set_sys_message(user['userID'], 2,
                                        '您已被管理员 ' + user['nickname'] + ' 踢出群组 ' + group['name'] + ' !', user_id, '群聊通知')
                    return jsonify({'code': 1, 'msg': 'success'})
                return jsonify({'code': -1, 'msg': 'unable to ban user'})
            return jsonify({'code': 0, 'msg': 'unexpected user'})
        return jsonify({'code': 0, 'msg': 'unexpected user'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/back_get_groups')
def back_get_groups():
    """
    后台获取群聊
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        groups = db.get({}, 'groups', 0)
        for value in groups:
            create = db.get({'userID': value['userID']}, 'users')
            if create:
                value.update({'nickname': create['nickname']})
        return jsonify({'code': 1, 'msg': 'success', 'data': groups})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/delete_group')
def delete_group():
    """
    清除群聊
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        group_id = request.values.get('group_id')
        flag = db.update({'groupID': group_id}, {'state': -1}, 'groups')
        if flag:
            set_user_action(user['userID'], group_id, 36)
            set_sys_message(user['userID'], 1, '您创建的群组 ' + flag['name'] + ' 已被管理员解散！', flag['userID'], '群聊通知')
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/group/exit_group')
def exit_group():
    """
        退出群聊
    """
    token = request.values.get('token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        group_id = request.values.get('group_id')
        group = db.get({'groupID': group_id}, 'groups')
        if group:
            flag = db.delete({'userID': user['userID'], 'groupID': group_id}, 'group_members')
            if flag:
                call_group_members(0, '用户 ' + user['nickname'] + ' 已退出群聊 ' +
                                   group['name'] + '', group_id)
                return jsonify({'code': 1, 'msg': 'success'})
            return jsonify({'code': -1, 'msg': 'unable to delete'})
        return jsonify({'code': -2, 'msg': 'unknow group'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    活动接口
"""


@app.route('/api/activities/add_activity')
def add_activity():
    """
    添加新活动
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        title = request.form['title']
        cover = request.form['cover']
        url = request.form['url']
        act_type = request.form['type']
        flag = db.insert({'title': title, 'cover': cover, 'url': url, 'type': act_type, 'userID': user['userID']},
                         'activities')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/activities/get_activities')
def get_activities():
    """
    获取活动
    :return:
    """
    act_type = request.values.get('type')
    db = Database()
    activity = db.get({'type': act_type, 'state': 0}, 'activities', 0)
    return jsonify({'code': 1, 'msg': 'success', 'data': activity})


@app.route('/api/activities/get_all_activities')
def get_all_activities():
    """
    获取所有活动
    :return:
    """
    db = Database()
    activity = db.get({}, 'activities_info')
    return jsonify({'code': 1, 'msg': 'success', 'data': activity})


@app.route('/api/activities/edit_activity')
def edit_activity():
    """
    修改活动
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        title = request.form['title']
        cover = request.form['cover']
        url = request.form['url']
        act_type = request.form['type']
        act_id = request.form['id']
        flag = db.update({'activityID': act_id},
                         {'title': title, 'cover': cover, 'url': url, 'type': act_type, 'userID': user['userID']},
                         'activities')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to update'})
    return jsonify({'code': 1, 'msg': 'unexpected user'})


@app.route('/api/activities/delete_activity')
def delete_activity():
    """
    删除活动
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token}, 'users')
    if user:
        act_id = request.values.get('id')
        flag = db.update({'activityID': act_id}, {'state': -1}, 'activities')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to update'})
    return jsonify({'code': 1, 'msg': 'unexpected user'})


"""
    标签接口
"""


@app.route('/api/tags/get_first_tag')
def get_first_tag():
    """
    获取tag
    :return:
    """
    db = Database()
    tags = db.get({'type': 1}, 'tags', 0)
    return jsonify({'code': 1, 'msg': 'success', 'data': tags})


@app.route('/api/tags/get_child_tag')
def get_child_tag():
    """
    获取tag下的子tag
    :return:
    """
    db = Database()
    tag_id = request.values.get('tag_id')
    tags = db.get({'father': tag_id}, 'tags', 0)
    return jsonify({'code': 1, 'msg': 'success', 'data': tags})


@app.route('/api/tags/get_tag_recommend')
def get_tag_recommend():
    """
    键入tag时获取推荐
    :return:
    """
    db = Database()
    tag_id = request.values.get('tag_id')
    tag = request.values.get('tag')
    token = request.values.get('token')
    user = db.get({'token': token}, 'users')
    if user:
        tags = db.sql('SELECT * FROM tags  WHERE name LIKE "%' + str(tag) + '%" AND father = "' + str(tag_id) + '"')
        if tags:
            return jsonify({'code': 1, 'msg': 'success', 'data': tags})
        if get_level(user['exp']) >= 3:
            return jsonify({'code': 1, 'msg': 'success', 'data': [{'name': tag, 'id': -1}]})
        return jsonify({'code': 1, 'msg': 'success', 'data': []})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/tags/add_tag', methods=['POST'])
def add_tag():
    """
    添加tag
    :return:
    """
    db = Database()
    token = request.form['token']
    user = db.get({'token': token}, 'users')
    if user:
        name = request.form['name']
        tag_type = request.form['tag_type']
        father = request.form['father']
        if db.get({'name': name, 'type': tag_type, 'father': father}, 'tags'):
            return jsonify({'code': -2, 'msg': 'tag is already exist'})
        flag = db.insert({'name': name, 'type': tag_type, 'father': father}, 'tags')
        if flag:
            tag_id = db.get({'name': name, 'type': tag_type, 'father': father}, 'tags')
            return jsonify({'code': 1, 'msg': 'success', 'data': tag_id})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/tags/get_tag_tree')
def get_tag_tree():
    """
    获取tag树
    :return:
    """
    db = Database()
    tags = db.get({'type': 1}, 'tags', 0)
    for value in tags:
        children = db.get({'father': value['id']}, 'tags', 0)
        value.update({'children': children})
    return jsonify({'code': 1, 'msg': 'success', 'data': tags})


@app.route('/api/tags/delete_tag')
def delete_tag():
    """
    清除tag
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        tag_id = request.values.get('tag_id')
        flag = db.delete({'id': tag_id}, 'tags')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to delete'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/tags/edit_tag', methods=['POST'])
def edit_tag():
    """
    修改标签
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        tag_id = request.form['id']
        name = request.form['name']
        tag_type = request.form['type']
        flag = db.update({'id': tag_id}, {'name': name, 'type': tag_type}, 'tags')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/tags/merge_tags')
def merge_tags():
    """
    合并标签
    :return:
    """
    token = request.headers.get('X-Token')
    db = Database()
    user = db.get({'token': token, 'usergroup': 0}, 'users')
    if user:
        tag_id = request.values.get('tag_id')
        merge_id = request.values.get('merge_id')
        question = db.get({}, 'questions', 0)
        for value in question:
            if value['tags'] is None:
                continue
            tags = value['tags'].split(',')
            if merge_id in tags:
                tags.remove(merge_id)
                if tag_id not in tags:
                    tags.append(tag_id)
            db.update({'questionID': value['questionID']}, {'tags': ','.join(tags)}, 'questions')
        answer = db.get({}, 'answers', 0)
        for value in answer:
            if value['tags'] is None:
                continue
            tags = value['tags'].split(',')
            if merge_id in tags:
                tags.remove(merge_id)
                if tag_id not in tags:
                    tags.append(tag_id)
            db.update({'answerID': value['answerID']}, {'tags': ','.join(tags)}, 'answers')
        article = db.get({}, 'article', 0)
        for value in article:
            if value['tags'] is None:
                continue
            tags = value['tags'].split(',')
            if merge_id in tags:
                tags.remove(merge_id)
                if tag_id not in tags:
                    tags.append(tag_id)
            db.update({'articleID': value['articleID']}, {'tags': ','.join(tags)}, 'article')
        demand = db.get({}, 'demands')
        for value in demand:
            if value['tags'] is None:
                continue
            tags = value['tags'].split(',')
            if merge_id in tags:
                tags.remove(merge_id)
                if tag_id not in tags:
                    tags.append(tag_id)
            db.update({'demandID': value['demandID']}, {'tags': ','.join(tags)}, 'demands')
        flag = db.delete({'id': merge_id}, 'tags')
        if flag:
            return jsonify({'code': 1, 'msg': 'success'})
        return jsonify({'code': -1, 'msg': 'unable to merge'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/tags/back_add_tag', methods=['POST'])
def back_add_tag():
    """
    添加tag
    :return:
    """
    db = Database()
    token = request.headers.get('X-Token')
    user = db.get({'token': token}, 'users')
    if user:
        name = request.form['name']
        tag_type = request.form['tag_type']
        if db.get({'name': name, 'type': tag_type}, 'tags'):
            return jsonify({'code': -2, 'msg': 'tag is already exist'})
        flag = db.insert({'name': name, 'type': tag_type}, 'tags')
        if flag:
            tag_id = db.get({'name': name, 'type': tag_type}, 'tags')
            return jsonify({'code': 1, 'msg': 'success', 'data': tag_id})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


@app.route('/api/tags/back_add_child_tag', methods=['POST'])
def back_add_child_tag():
    """
    添加tag
    :return:
    """
    db = Database()
    token = request.headers.get('X-Token')
    user = db.get({'token': token}, 'users')
    if user:
        name = request.form['name']
        tag_type = request.form['tag_type']
        father = request.form['father']
        if db.get({'name': name, 'type': tag_type, 'father': father}, 'tags'):
            return jsonify({'code': -2, 'msg': 'tag is already exist'})
        flag = db.insert({'name': name, 'type': tag_type, 'father': father}, 'tags')
        if flag:
            tag_id = db.get({'name': name, 'type': tag_type, 'father': father}, 'tags')
            return jsonify({'code': 1, 'msg': 'success', 'data': tag_id})
        return jsonify({'code': -1, 'msg': 'unable to insert'})
    return jsonify({'code': 0, 'msg': 'unexpected user'})


"""
    其他
"""


@app.route('/api/other/check_update')
def check_update():
    """
    检查更新
    :return:
    """
    with open('/etc/project-agent/API/version.json', 'r', encoding='utf-8') as file:
        version = json.load(file)
        return jsonify(version)


if __name__ == '__main__':
    # 开启调试模式，修改代码后不需要重新启动服务即可生效
    # 请勿在生产环境下使用调试模式
    # Flask服务将默认运行在localhost的5000端口上

    # with open('static\\upload\\36.txt', 'rb') as file:
    #     result = pred(file.read())
    #     print(result[0])
    # app.run(threaded=True, host='0.0.0.0', port=5000, ssl_context=(
    #     '/etc/letsencrypt/live/hanerx.tk/fullchain.pem', '/etc/letsencrypt/live/hanerx.tk/privkey.pem'))
    app.run(host='0.0.0.0', port=5000)
