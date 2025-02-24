import hashlib
from API.config import *
import pymysql


def generate_password(original_password):
    """
    加密函数，使用sha256对密码进行加密处理
    :param original_password: 原密码
    :return: 加密后的二进制字符串
    """
    salt = 'project_agent'  # 加盐
    sha256 = hashlib.sha256()  # 创建sha256对象
    sha256.update((original_password + salt).encode('utf-8'))  # 加载密码
    return sha256.hexdigest()  # 返回十六进制字符串


class Database(object):
    MYSQL_NULL = ' is null'
    MYSQL_INSERT_NULL = 'null'

    # __init__方法将在类实例创建时执行，可用于完成数据库的初始化操作
    def __init__(self, host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, db=MYSQL_DB):
        try:
            # 连接数据库，之后在类方法中使用 self.db 调用
            self.db = pymysql.connect(
                host=host,
                port=port,
                user=user,
                passwd=password,
                db=db,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
        except pymysql.MySQLError as e:
            print(e.args)  # 这里将错误信息打印到控制台，实际开发时应该写入日志文件

    # __del__方法将在类实例被销毁时执行，此处用于关闭数据库，实际上python会自动完成关闭和清理操作
    def __del__(self):
        self.db.close()

    # 实现一个INSERT方法，此处将演示pyCharm常用的方法注释功能
    def insert(self, data, table):
        """
        将数据添加到表
        :param data: 待添加的数据，类型为dict
        :param table: 目标table的名称
        :return: 操作是否成功
        """
        # 构造键值成分
        keys = '`' + '`, `'.join(data.keys()) + '`'
        list2 = []
        list3 = []
        for key, values in data.items():
            if values == self.MYSQL_INSERT_NULL:
                list2.append(values)
            else:
                list2.append('%s')
                list3.append(str(values))
        values = ', '.join(list2)
        # 插入数据
        try:
            with self.db.cursor() as cursor:
                # 构造sql语句
                sql_query = 'INSERT INTO %s (%s) VALUES (%s)' % (table, keys, values)
                cursor.execute(sql_query, list3)
            # 提交语句
            self.db.commit()
            return True
        except pymysql.MySQLError as e:
            print(e.args)
            return False

    def get(self, data, table, type=1):
        """
        获取数据库数据
        :param type: int 返回种类 1 = 自动返回数组或单个dist 0 = 全部返回数组(用于遍历)
        :param data: dist 待查寻的数据
        :param table: 目标table的名称
        :return: list 查询到的内容 当无数据时返回空数组，单个数据时按照type种类返回单个dist或数组，多个数据时固定返回数组
        """
        try:
            with self.db.cursor() as cursor:
                if not data:  # 判断data是否为空
                    sql_query = 'SELECT * FROM %s' % table  # 构造sql语句
                    cursor.execute(sql_query)
                    results = cursor.fetchall()
                    return results  # 返回所有数据
                list1 = []
                for key, values in data.items():
                    if values == self.MYSQL_NULL:
                        list1.append(key + self.MYSQL_NULL)
                    else:
                        list1.append('`' + key + '`="' + str(values) + '"')
                where = ' AND '.join(list1)
                sql_query = 'SELECT * FROM %s WHERE %s' % (table, where)  # 构造sql语句
                sql_query.replace('\\', '\\\\')
                cursor.execute(sql_query)
                results = cursor.fetchall()
                if len(results) == 1 and type == 1:
                    return results[0]  # 返回单个数组
                if not results and type == 0:
                    return []
                return results  # 返回多个数组
        except pymysql.MySQLError as e:
            print(e.args)
            return []  # 返回空数组

    def update(self, where_list, data, table):
        """
        更新数据库数据
        :param where_list: dist 需要更新的数据库所在
        :param data: dist 需要更新的内容
        :param table: 目标表名
        :return: dist 更新后的表单 单个dist
        """
        try:
            with self.db.cursor() as cursor:
                list1 = []
                for key, values in where_list.items():
                    list1.append(str(key) + ' = "' + str(values) + '"')
                list2 = []
                for key, values in data.items():
                    list2.append(key + ' = "' + str(values) + '"')
                where = ' AND '.join(list1)
                update = ' , '.join(list2)
                sql_query = 'UPDATE %s SET %s WHERE %s' % (table, update, where)  # 构造sql语句
                cursor.execute(sql_query)
                self.db.commit()
                where_list.update(data)  # 更新查询选
                return self.get(where_list, table)  # 调用get返回更新后的信息
        except pymysql.MySQLError as e:
            print(e.args)
            return []

    def update_new(self, where_list, data, table):
        """
        更新数据库数据
        :param where_list: dist 需要更新的数据库所在
        :param data: dist 需要更新的内容
        :param table: 目标表名
        :return: dist 更新后的表单 单个dist
        """
        try:
            with self.db.cursor() as cursor:
                list1 = []
                for key, values in where_list.items():
                    list1.append(str(key) + ' = "' + str(values) + '"')
                list2 = []
                for key, values in data.items():
                    list2.append(key + ' = "' + str(values) + '"')
                where = ' AND '.join(list1)
                update = ' , '.join(list2)
                sql_query = 'UPDATE %s SET %s WHERE %s' % (table, update, where)  # 构造sql语句
                cursor.execute(sql_query)
                self.db.commit()
                # where_list.update(data)  # 更新查询选项
                for value in data.keys():
                    for item in where_list.keys():
                        if value == item:
                            where_list.update({value: data[value]})
                return self.get(where_list, table)  # 调用get返回更新后的信息
        except pymysql.MySQLError as e:
            print(e.args)
            return []

    def delete(self, where_list, table):
        """
        清除数据库数据
        :param where_list: dist 需要更新的数据库所在
        :param table: 目标表名
        :return: boolean
        """
        try:
            with self.db.cursor() as cursor:
                list1 = []
                for key, values in where_list.items():
                    if values == self.MYSQL_NULL:
                        list1.append(key + self.MYSQL_NULL)
                    else:
                        list1.append(key + '="' + str(values) + '"')
                where = ' AND '.join(list1)
                sql_query = 'DELETE FROM %s WHERE %s' % (table, where)  # 构造sql语句
                sql_query.replace('\\', '\\\\')
                cursor.execute(sql_query)
                self.db.commit()
                return True
        except pymysql.MySQLError as e:
            print(e.args)
            return False  # 返回空数组

    def count(self, data, table):
        """
        统计特定条件下的数据总数
        :param data: dist 筛选条件
        :param table: 目标表名
        :return: int 统计数据
        """
        try:
            with self.db.cursor() as cursor:
                if not data:  # 判断data是否为空
                    sql_query = 'SELECT COUNT(*) FROM %s' % table
                    cursor.execute(sql_query)
                    results = cursor.fetchall()
                    return results[0]['COUNT(*)']  # 返回所有数据
                list1 = []
                for key, values in data.items():
                    list1.append('`' + key + '`="' + str(values) + '"')
                where = ' AND '.join(list1)
                sql_query = 'SELECT COUNT(*) FROM %s WHERE %s' % (table, where)
                cursor.execute(sql_query)
                results = cursor.fetchall()
                return results[0]['COUNT(*)']  # 返回所有数据
        except pymysql.MySQLError as e:
            print(e.args)
            return -1  # 报错

    def like(self, data, table, type=0):
        """
        模糊搜索
        :param data: 模糊搜索数据
        :param table: 目标表名
        :return:
        """
        try:
            with self.db.cursor() as cursor:
                if not data:  # 判断data是否为空
                    return self.get(data, table)
                list1 = []
                for key, values in data.items():
                    if values == self.MYSQL_NULL:
                        list1.append(key + self.MYSQL_NULL)
                    else:
                        list1.append(key + ' LIKE \'%' + str(values) + '%\'')
                where = ' AND '.join(list1)
                sql_query = 'SELECT * FROM %s WHERE %s' % (table, where)  # 构造sql语句
                cursor.execute(sql_query)
                results = cursor.fetchall()
                if len(results) == 1 and type == 1:
                    return results[0]  # 返回单个数组
                return results  # 返回多个数组
        except pymysql.MySQLError as e:
            print(e.args)
            return []  # 报错

    def sql(self, str, type=0):
        """
        直接运行sql语句
        :param str: sql语句
        :return:
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute(str)
                results = cursor.fetchall()
                if len(results) == 1 and type == 1:
                    return results[0]
                return results
        except pymysql.mySQLError as e:
            print(e.args)
            return []

    def vague(self, data, table, type=0):
        """
        更加模糊的搜索
        :param data: 模糊搜索数据
        :param table: 目标表名
        :return:
        """
        try:
            with self.db.cursor() as cursor:
                if not data:  # 判断data是否为空
                    return self.get(data, table)
                list1 = []
                for key, values in data.items():
                    if values == self.MYSQL_NULL:
                        list1.append(key + self.MYSQL_NULL)
                    else:
                        if isinstance(values, str):
                            str_use = ''
                            if len(list1) == 0:
                                str_use = (key + ' LIKE \'%')
                            for single in values:
                                str_use += single + '%'
                            str_use += '\''
                            list1.append(str_use)
                        else:
                            list1.append(key + ' LIKE \'%' + str(values) + '%\'')

                where = ' AND '.join(list1)
                sql_query = 'SELECT * FROM %s WHERE %s' % (table, where)  # 构造sql语句
                cursor.execute(sql_query)
                results = cursor.fetchall()
                if len(results) == 1 and type == 1:
                    return results[0]  # 返回单个数组
                return results  # 返回多个数组
        except pymysql.MySQLError as e:
            print(e.args)
            return []  # 报错
