from WSG.WordSegmentation import pred
import numpy as np
from enum import  Enum

def cosine_similarity(vector1, vector2):
    """
    计算出余弦相似度,越接近1越相似
    :param vector1: 用户的评分矩阵，一维
    :param vector2: 某个其他用户的评分矩阵，一维
    :return: 用户和某个用户的兴趣相似度
    """
    dot_product = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vector1, vector2):
        dot_product += (float(a) * float(b))
        norm_a += float(a) ** 2
        norm_b += float(b) ** 2
    if norm_a == 0.0 or norm_b == 0.0:
        return 0
    else:
        norm_a = norm_a ** 0.5
        norm_b = norm_b ** 0.5
        return round(dot_product / (norm_a * norm_b), 4)


def set_similarity_vec(path,similar_path,rect_file,id_list_name,name="similarity_vector.txt"):
    """
    计算相似矩阵

    :param rect_file: 评分矩阵文件路径, 矩阵形式为 对象ID:id值 rate:评分者ID-评分值,评分者ID-评分值...
    :param vec: 待算的的向量，可以为 用户评分列表或者文章列表
    :param name: 存储的文件名称
    :return: 返回规模为 用户*用户 或者 文章*文章 的相似度矩阵,物品的ID列表
    """
    item_ids = []
    rates = []

    with open(path + rect_file, "r") as f:
        lines = f.readlines()
        for i in range(len(lines)):
            lines[i].replace("\n", "")
            a = lines[i].split(" ")
            id = a[0].split(":")
            id = int(id[1])
            item_ids.append(id)

            rt = a[1].split(":")
            rt = rt[1].split(";")
            rtt = []
            for i in range(len(rt)):
                if (i % 2 == 1):
                    rtt.append(rt[i])
            rates.append(rtt)

    simi_vec = [[0 for i in range(len(rates))] for j in range(len(rates))]
    with open(similar_path + name, "w") as f:
        for i in range(len(rates)):
            for j in range(len(rates)):
                simi_vec[i][j] = cosine_similarity(rates[i], rates[j])
                f.write(str(simi_vec[i][j]) + ",")
            f.write("\n")
    f.close()

    with open(similar_path + id_list_name,"w") as f:
        for i in range(len(item_ids)):
            f.write(str(item_ids[i]) + ",")

    return simi_vec, item_ids


def read_similarity_vec(path,dir="similarity_vector.txt",id_file=""):
    """
    读取文件中存储的相似度矩阵
    :param dir: 读取的文件路径，默认为本目录下的similarity_vector.txt
    :return: 相似度矩阵,id列表
    """
    id_list = []

    with open(path + dir, 'r') as f:
        lines = f.readlines()
        simi_vec = [[0 for i in range(len(lines))] for j in range(len(lines))]
        for i in range(len(lines)):
            line = lines[i].split(",")
            for j in range(len(line) - 1):
                simi_vec[i][j] = float(line[j])

    with open(path + id_file) as f:
        lines = f.readlines()
        line = lines[0].split(",")
        for i in range(len(line)):
            id_list.append(line[i])
    id_list.pop()
    return simi_vec,id_list


def interest_value(similar, rate_vec):
    """
    获取兴趣程度，作为protected方法使用
    :param similar: 该用户和目标用户的兴趣相似度,数字
    :param rate_vec: 该用户的评分矩阵，一维
    :return: 每个评价对象的兴趣程度 ,一维
    """
    interest_vec = []
    for i in range(len(rate_vec)):
        interest_vec.append(similar * rate_vec[i])
    return interest_vec


def most_similar(simi_vec, item_ids, id, num=1):
    """
    根据相似度矩阵获取最相似的项
    :param simi_vec: 相似度矩阵
    :param item_ids: ID列表
    :param id: 比较的对象ID
    :param num: 返回的ID数量
    :return: 最相似项的ID序列，相似度降序
    """
    most_val = 10000
    most_idx = []
    idx = 0
    # 转换成整数
    id = int(id)
    # 由于矩阵横竖对称，id在ID列表的第几位，对应id的相似度向量肯定也在第几位，idx记录位数
    for it in item_ids:
        if (int(it) == id):
            break
        idx += 1

    # 若idx大于ID列表的长度，则说明没找到，直接返回空值
    if idx >= len(item_ids):
        return []

    # 遍历该物品的每个相似度，i的值也是该位置的物品在item_ids里面对应位置
    for i in range(len(simi_vec[idx])):
        most_idx = i
        for j in range(i + 1, len(simi_vec[idx])):
            if (abs(simi_vec[idx][most_idx] - 1) > abs(simi_vec[idx][j] - 1)):
                most_idx = j
        if most_idx != i:
            temp = simi_vec[idx][i]
            simi_vec[idx][i] = simi_vec[idx][most_idx]
            simi_vec[idx][most_idx] = temp

            temp = item_ids[i]
            item_ids[i] = item_ids[most_idx]
            item_ids[most_idx] = temp

    if int(num) > len(item_ids) - 1:
        num = len(item_ids) - 1
    return item_ids[1:num + 1]


def most_interest(similar_vec, rate_vec, k=1, m=1):
    """
    获取目标用户最感兴趣的几个对象
    :param similar_vec: 其他用户和目标用户的兴趣相似度矩阵，一维
    :param rate_vec: 用户的评分矩阵，二维，一维对应某用户，一维对应该用户的评分
    :param k: 选取其他用户的个数，按相似度程度降序排列,默认为1
    :param m: 输出的元组个数，默认为1
    :return: 元组，格式为 (评论对象下标，兴趣度)
    """

    # 兴趣数组，待计算
    total_interest = []
    # 初始化长度，长度为评价向量的长度，数组内每一个元素对应每个对象的兴趣程度
    for i in range(len(rate_vec[0])):
        total_interest.append(0)

    # 将相关的数据整合到同一个数据结构内，便于之后的处理
    together = sorted(list(zip(list(zip(range(len(similar_vec)), similar_vec)), rate_vec)), key=lambda item: item[0][1])
    # 选取前k个最相关的其他用户
    together = together[0:k]

    # 根据公式计算  用户u对物品i的感兴趣程度  P(u,i) = ∑S(u,k)∩N(i)  Wuv*Rvi
    # S(u, K)包含和用户u兴趣最接近的K个用户， N(i)是对物品i有过行为的用户集合，
    # w_uv是用户u和用户v的兴趣相似度， r_vi代表用户v对物品i的兴趣度
    for i in range(len(together)):
        now_vec = interest_value(together[i][0][1], together[i][1])
        for j in range(len(now_vec)):
            total_interest[j] += now_vec[j]

    zip_interest = dict(zip(range(len(total_interest)), total_interest))
    # 排序，选出最感兴趣的m类物品
    sorted_interest = sorted(zip_interest.items(), key=lambda item: item[1], reverse=True)
    return sorted_interest[:m]

def read_rate_rect(type,id):
    """
    读取指定的评分
    :param type: 读取的类别，为CF_TYPE枚举量  1-用户  2-问题  3-文章
    :param id: 根据该ID读取的评分
    :return: 评分向量
    """
    rate_dir = CF_PATH + RATE_DIR
    # 确认读取路径
    if type == CF_TYPE.USER:
        rate_dir += USER_RATE_NAME
    elif type == CF_TYPE.QUESTION:
        rate_dir += QUESTION_RATE_NAME
    elif type == CF_TYPE.ARTICLE:
        rate_dir += ARTICLE_RATE_NAME

    all_rates = {}
    with open(rate_dir,'r') as f:
        lines = f.readlines()
        for i in range(len(lines)):
            lines[i].replace("\n", "")
            # a包含ID和评分信息
            a = lines[i].split(" ")
            # 获取ID信息
            read_id = a[0].split(':')
            read_id = read_id[1]
            # 若该行评分信息不是对于ID进行的，则跳过
            if(read_id not in id):
                continue
            info = a[1].split(':')
            info = info[1].split(';')

            arr = []
            for index in range(0,len(info),2):
                rates = {}
                rates[info[index]] = info[index+1]
                arr.append(rates)

            all_rates[read_id] = arr
    # 返回的对象，{
    #   用户id值：[{物品id值:评分},{物品id值:评分},...],
    #   用户id值：[{物品id值:评分},{物品id值:评分},...],
    #   用户id值：[{物品id值:评分},{物品id值:评分},...],
    # }
    return all_rates


def cf(self_vec, others_vec, k=1, m=1, item_vec=[]):
    """
    用cf算法推荐对象
    :param self_vec: 需要进行推荐的用户评分矩阵,一维[ , , ]
    :param others_vec: 其他用户的评分矩阵,二维[ [] , [] ]
    :param k: 选取其他用户的个数，按相似度程度降序排列
    :param m: 输出的元组个数
    :param item_vec: 如果该参数存在，则直接输出推荐对象对应下标的名称，否则输出下标
    :return: 推荐的对象
    """
    # 相似度矩阵，待计算
    similar_vec = []
    rate_vec = [self_vec] + others_vec
    for i in range(len(rate_vec)):
        if i == 0:
            # 以第一个用户为目标用户，第一次循环计算自己的相似度，adjusted_cosin算法得到的值越接近1，相似度越大，这里设置为1-1=0
            # 表示最大相似度
            similar_vec.append(0)
        else:
            # 以第一个用户为目标用户，计算其他用户的相似度
            similar_vec.append(abs(cosine_similarity(rate_vec[0], rate_vec[i]) - 1))

    # 获取目标用户最感兴趣的对象类型
    most_interest_vec = most_interest(similar_vec[1:], rate_vec[1:], k, m)
    # 输出类型
    # 当用户基数少的时候，由于cos计算结果可能都很大，即使选取最相似的其他用户进行推荐，也会形成推荐不准确
    # 比如这个例子下的结果"财经",目标用户对财经的评价很低，但是依然推荐了财经
    data = []
    for i in range(m):
        if len(item_vec) != 0:
            data.append(item_vec[most_interest_vec[i][0]])
        else:
            data.append(most_interest_vec[i][0])
    return data


def item_cf(dirs,id_file, target, num):
    """
    基于物品的cf算法
    :param dirs: 物品相似度矩阵文件名
    :param target: 为某个物品推荐，该物品的ID
    :param num: 推荐几个
    :return: 推荐的物品ID序列
    """

    simi_vec,item_ids = read_similarity_vec(CF_PATH,dirs,id_file)

    idx = most_similar(simi_vec, item_ids, target, num)
    return idx


def user_cf(dirs,id_file, target, num):
    """
    基于用户的cf 算法
    :param dirs: 用户的相似度矩阵文件名
    :param id_file: 用户的id序列文件
    :param target: 为某个用户推荐
    :param num: 推荐个数
    :return: 推荐的用户和相应物品
    """
    # 获取用户相似度矩阵和用户id列表
    simi_vec,item_ids = read_similarity_vec(CF_PATH,dirs,id_file)
    # 得到推荐的相似用户
    idx = most_similar(simi_vec,item_ids,target,int(num))

    # 获得推荐用户的评分信息
    rate = read_rate_rect(CF_TYPE.USER,idx)
    # 返回的对象，按评分降序排列{
    #   用户id值：[{物品id值:评分},{物品id值:评分},...],
    #   用户id值：[{物品id值:评分},{物品id值:评分},...],
    #   用户id值：[{物品id值:评分},{物品id值:评分},...],
    # }
    keys = rate.keys()
    for key in keys:
        for i in range(len(rate[key])-1):
            biggest = i
            for j in range(i+1,len(rate[key])):
                biggest_key = ""
                now_key = ""
                for k in rate[key][biggest].keys():
                    biggest_key = k
                for k in rate[key][j].keys():
                    now_key = k

                if float(rate[key][biggest][biggest_key]) < float(rate[key][j][now_key]):
                    biggest = j
            if biggest != j:
                swap = rate[key][biggest]
                rate[key][biggest] = rate[key][i]
                rate[key][i] = swap

    return rate


"""
常量区
"""

CF_PATH = "/etc/project-agent/CF/"
# CF_PATH = "../CF/"

RATE_DIR = "rate_rect/"
SIMILAR_DIR = "similar_rect/"

USER_RATE_NAME = "user_rate_rect.txt"
USER_ID_NAME = "user_id_list.txt"
USER_SIMILAR_NAME = "user_similar_rect.txt"

ARTICLE_RATE_NAME = "aritcle_rate_rect.txt"
ARTICLE_ID_NAME = "article_id_list.txt"
ARTICLE_SIMILAR_NAME = "article_similar_rect.txt"

QUESTION_RATE_NAME = "question_rate_rect.txt"
QUESTION_ID_NAME = "question_id_list.txt"
QUESTION_SIMILAR_NAME = "question_similar_rect.txt"

class CF_TYPE(Enum):
    USER = 1
    QUESTION = 2
    ARTICLE = 3


if __name__ == '__main__':
    set_similarity_vec('./rate_rect/question_rate_rect.txt')
