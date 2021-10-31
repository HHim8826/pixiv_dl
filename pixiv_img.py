#-*- coding: utf-8 -*
import requests
import os
import re
import toml
from tqdm import tqdm
from json.decoder import JSONDecodeError
# from pprint import pprint

# get pixiv_cookie.toml
def config_pixiv():
    cfg = toml.load(os.path.expanduser('./pixiv_cookie.toml'))       
    return cfg
    
# mark folder
def mark_dir(name:str,search=None,ranking=None,r18mode=False):
    if ranking == 'daily':
        mode = 'daily'
        part = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    elif ranking == 'weekly':
        mode = 'weekly'
        part = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    elif ranking == 'monthly':
        mode = 'monthly'
        part = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    elif ranking == 'rookie':
        mode = 'rookie'
        part = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    elif ranking == 'original':
        mode = 'original'
        part = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    elif ranking == 'female':
        mode = 'female'
        part = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    elif ranking == 'daily_r18':
        if r18mode == True:
            mode = 'daily_r18'
            part = f'./img/R18/{name}的作品'
            try:
                os.makedirs(part)
            except FileExistsError:
                pass
    elif ranking == 'male':
        mode = 'male'
        part = f'./img/{mode}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass   
    
    
    elif search == None:    
        part = f'./img/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    elif search != None and isinstance(search,str):
        part = f'./img/{search}/{name}的作品'
        try:
            os.makedirs(part)
        except FileExistsError:
            pass
    

# get json data
def pixiv_get(id,cfg:dict) -> str:
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    
    url = f'https://www.pixiv.net/ajax/illust/{id}/pages'
    
    req = requests.get(url,headers=headers)
    req = req.json()
    # print(req)
    body_data = req['body']
    
    return body_data

# download img
def dl_img(id:int or list,cfg:dict,search=None,ranking=None,r18mode=False,AllInOneDir=False) -> bytes:
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    # 判斷 id 是否列表
    if type(id) == list:
        for i in id:               
            # get json data
            data_json = pixiv_get(i[0],cfg)           
            if AllInOneDir == True:
                for url in tqdm(data_json):
                    url = url['urls']['original']
                    re_name = url.split("/")
                    req = requests.get(url,headers=headers)
                    with open(f'./img/{re_name[-1]}','wb') as f:
                                f.write(req.content)           
            else:
                # get folder name
                folder_name = i[1]
                # mark folder
                if search != None:
                    mark_dir(folder_name,search)
                elif ranking != None:
                    if r18mode == True:
                        mark_dir(folder_name,ranking=ranking,r18mode=True)
                    else:
                        mark_dir(folder_name,ranking=ranking)   
                for iter1 in tqdm(data_json):
                    # get original url
                    iter1 = iter1['urls']['original']
                    # get file name
                    n_name = iter1.split("/")
                    req = requests.get(iter1,headers=headers)               
                    # save img
                    if search != None:
                        with open(f'./img/{search}/{folder_name}的作品/{n_name[-1]}','wb') as f:
                            f.write(req.content)
                    elif ranking != None:
                        if r18mode == True:
                            with open(f'./img/R18/{folder_name}的作品/{n_name[-1]}','wb') as f:
                                f.write(req.content)
                        else:
                            with open(f'./img/{ranking}/{folder_name}的作品/{n_name[-1]}','wb') as f:
                                f.write(req.content)                    
        return 'DONE'
            
    folder_name = get_user(id)         
    data_json = pixiv_get(id,cfg)
    mark_dir(folder_name)
    for i in tqdm(data_json):
        i = i['urls']['original']
        n_name = i.split("/")
        if AllInOneDir == True:
            req = requests.get(i,headers=headers)
            with open(f'./img/{n_name[-1]}','wb') as f:
                f.write(req.content)
        else:
            req = requests.get(i,headers=headers)
            
            
            with open(f'./img/{folder_name}的作品/{n_name[-1]}','wb') as f:
                f.write(req.content)
    return 'DONE'

# get id list
def pixiv_search(name:str,cfg:dict,mode=0) -> list:
    # cookie == None ?
    class_json = ['illust','popular']   
    
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    
    # save data
    id_list = []
    # https://www.pixiv.net/ajax/search/illustrations/甘雨(原神)?word=甘雨(原神)&order=date_d&mode=all&p=1&s_mode=s_tag_full&type=illust_and_ugoira&lang=zh_tw
    url = f'https://www.pixiv.net/ajax/search/illustrations/{name}'
    
    if mode == 0:
        params = {
            'word' : name,
            'mode' : 'all'
        }
    elif mode == 1:
        params = {
            'word' : name,
            'mode' : 'safe'
        }
    elif mode == 2:
        params = {
            'word' : name,
            'mode' : 'r18'
        }
    
    req = requests.get(url,headers=headers,params=params)
    # q= req
    req = req.json()
    
    # with open("pixiv/jsondata.json",'w') as f:
    #     f.write(q.text.encode().decode('unicode_escape').replace(r'\/',r'/'))     
    # print(req,url)   
    for json_tage in class_json:
        try:
            # get id
    
            body_data = req['body']['illust']['data']
            data_long = len(body_data)
            for i in range(data_long):
                id_num = body_data[i]['id']
                userName = body_data[i]['userName']
                userName = userName.replace(r"\u0027",'')
                userName = userName.replace(r"*",'')
                userName = userName.replace(r"/",'')
                id_list.append([id_num,userName])
                          
        except KeyError:

            # print(json_tage)
            
            body_data = req['body']['popular']['permanent']
            
            id_long = len(body_data)
            # print(id_long)
            for num in range(id_long): 
                id_num = body_data[num]['id']
                userName = body_data[num]['userName']
                userName = userName.replace(r"\u0027",'')
                userName = userName.replace(r"*",'')
                userName = userName.replace(r"/",'')
                id_list.append([id_num,userName])
            
                     
            body_data_1 = req['body']['popular']['recent']
            id_long_2 = len(body_data_1)
            # print(id_long_2)
            for num_2 in range(id_long_2):
                id_num_2 = body_data_1[num_2]['id']
                userName_2 = body_data_1[num_2]['userName'] 
                userName_2 = userName.replace(r"\u0027",'')
                userName_2 = userName.replace(r"*",'')
                userName_2 = userName.replace(r"/",'')
                id_list.append([id_num_2,userName_2])    
    search = name
    return id_list,search

# ['daily','weekly','monthly','rookie','original','female','daily_r18','male']
def ranking(page:int, cfg:dict,mode_num=0,r18mode=0):
    headers = {'referer' : "https://www.pixiv.net/ranking.php",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36",'Content-Type': 'application/json'}
    id_name_list = []
 
    if mode_num == 0:
        mode = 'daily'
    elif mode_num == 1:
        mode = 'weekly'
    elif mode_num == 2:
        mode = 'monthly'
    elif mode_num == 3:
        mode = 'rookie'
    elif mode_num == 4:
        mode = 'original'
    elif mode_num == 5:
        mode = 'female'
    elif mode_num == 6:
        if r18mode == 0:
            mode = 'daily_r18'
        elif r18mode == 1:
            mode = 'weekly_r18'
        elif r18mode == 2:
            mode = 'male_r18'
        elif r18mode == 3:
            mode = 'female_r18'
    elif mode_num == 7:
        mode = 'male'
        
    for page_num in range(page):
        
        # ?p={page_num+1}&format=json
        url = f'https://www.pixiv.net/ranking.php'
        
        params = {
            'p' : page_num+1,
            'format' : 'json',
            'mode' : mode
        }
        req = requests.get(url ,headers=headers,params=params)
        req = req.json()
        
        json_data = req['contents']
        times = len(json_data)
        for len_data in range(times):
            id_num = json_data[len_data]['illust_id']
            userName = json_data[len_data]['user_name']
            userName = userName.replace(r"\u0027",'')
            userName = userName.replace(r"*",'')
            userName = userName.replace(r"/",'')
            id_name_list.append([id_num,userName])
    
    if mode_num == 6:
        mode = 'daily_r18'
    return id_name_list,mode
                

# get name for id mode
def get_user(id:int) -> str:   
    url = f'https://www.pixiv.net/artworks/{id}'

    req = requests.get(url)
    text = req.text
    # print(text)
    # find name
    obj = re.compile(r'"name":"(?P<name>.*?)"')
    user_name = obj.finditer(text)

    # get name
    for it in user_name:
        name =  it.group('name')
    
    # del非法字符
    name = re.sub(r'\\"<>|:?','',name)
    # ' == \u0027
    name = name.replace(r"\u0027",'')
    name = name.replace(r"*",'')
    name = name.replace(r"/",'')
    return name    
    
def main():
    print('0:Pixiv_id mode\n1:Search mode\n2:ranking mode')
    mode = int(input('Mode:'))
    if mode == 0: #id mode
        cfg = config_pixiv()
        dl_img(int(input('Pixiv_id:')),cfg)
    elif mode == 1: #search mode
        cfg = config_pixiv()
        search = input("Search:")
        print('0:All\n1:Safe\n2:R18')
        mode_num = int(input('mode:'))
        id_list , search_name = pixiv_search(search,cfg,mode=mode_num)
        dl_img(id_list,cfg,search_name)
    elif mode == 2: #ranking mode?
        cfg = config_pixiv()
        # ['daily','weekly','monthly','rookie','original','female','daily_r18','male']
        page = int(input('Page:'))
        print('0:daily\n1:weekly\n2:monthly\n3:rookie\n4:original\n5:for female\n6:daily_r18(login)\n7:for male')
        ranking_num = int(input('ranking_mode:'))
        AllInOneDir = False
        if ranking_num == 6:
            try:
                print('0:daily_r18\n1:weekly_r18\n2:male_r18\n3:female_r18')
                r18mode = int(input("R18_mode:"))
                id_name_list , mode_ranking = ranking(page,cfg,mode_num=ranking_num,r18mode=r18mode)
                # print(mode_ranking)
                dl_img(id_name_list,cfg,ranking=mode_ranking,r18mode=True,AllInOneDir=AllInOneDir)
            except JSONDecodeError:
                exit('未登錄 . . .')             
        else:
            id_name_list , mode_ranking = ranking(page,cfg,mode_num=ranking_num)           
            dl_img(id_name_list,cfg,ranking=mode_ranking,AllInOneDir=AllInOneDir)
        

    # cfg = config_pixiv()
    # print(cfg['login']['cookie'])
    
    # id_list , search_name = pixiv_search('甘雨',cfg)
    # print(name)
    # print(id_list)
    # name = get_user(id_list)
    # mark_dir(name)
    
    # dl_img(id_list,cfg,search_name)
    
    # print(pixiv_get())
    
if __name__ == '__main__': 
    main()
    # mark_dir('a','b')

