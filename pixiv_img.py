#-*- coding: utf-8 -*
import requests
from pprint import pprint
import os
import re
from tqdm import tqdm
import toml

# get pixiv_cookie.toml
def config_pixiv():
    cfg = toml.load(os.path.expanduser('pixiv/pixiv_cookie.toml'))
    return cfg
    
# mark folder
def mark_dir(name:str):
    part = f'pixiv/img/{name}的作品'
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
def dl_img(id:int or list,cfg:dict) -> bytes:
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    # 判斷 id 是否列表
    if type(id) == list:
        for i in id:
            # get json data
            data_json = pixiv_get(i,cfg)
            # get folder name
            folder_name = get_user(i)
            # mark folder
            mark_dir(folder_name)
            for iter1 in tqdm(data_json):
                # get original url
                iter1 = iter1['urls']['original']
                # get file name
                n_name = iter1.split("/")
                req = requests.get(iter1,headers=headers)               
                # save img
                with open(f'pixiv/img/{folder_name}的作品/{n_name[-1]}','wb') as f:
                    f.write(req.content)
        return 'DONE'
            
    folder_name = get_user(id)          
    data_json = pixiv_get(id,cfg)
    mark_dir(folder_name)
    for i in tqdm(data_json):
        i = i['urls']['original']
        n_name = i.split("/")
        req = requests.get(i,headers=headers)
        
        
        with open(f'pixiv/img/{folder_name}的作品/{n_name[-1]}','wb') as f:
            f.write(req.content)
    return 'DONE'

# get id list
def pixiv_search(name:str,cfg:dict) -> list:
    # cookie == None ?
    if cfg['login']['cookie'] != "":
        # is login
        class_json = ['illustManga','popular']
    else:
        class_json = ['illust','popular']   
    
    headers = {'referer' : "https://www.pixiv.net/",'cookie' : f"{cfg['login']['cookie']}",'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36"}
    
    # save data
    id_list = []
    url = f'https://www.pixiv.net/ajax/search/top/{name}'
    
    req = requests.get(url,headers=headers)
    # q= req
    
    req = req.json()
    
    # with open("pixiv/jsondata.json",'w') as f:
    #     f.write(q.text.encode().decode('unicode_escape').replace(r'\/',r'/'))     
        
    for i in class_json:
        try:
            # get id
            id_num = req['body'][i]['data']
            for i in id_num:
                id_list.append(i['id'])
    

        except KeyError:
            # get id
            id_num = req['body'][i]['recent']
            id_long = len(id_num)
            # print(id_long)
            for num in range(id_long):   
                id_list.append(id_num[num]['id'])
            
                     
            id_num_2 = req['body'][i]['permanent']
            id_long_2 = len(id_num_2)
            # print(id_long_2)
            for num_2 in range(id_long_2):
                id_list.append(id_num_2[num_2]['id'])
                
    return id_list

# get name
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
    name = re.sub(r'\/*?"<>|:','',name)
    # ' == \u0027
    name = name.replace(r"\u0027",'')
    return name    
    
def main():
    cfg = config_pixiv()
    # print(cfg['login']['cookie'])
    
    id_list= pixiv_search(input("search:"),cfg)
    # print(id_list)
    # name = get_user(id_list)
    # mark_dir(name)
    
    dl_img(id_list,cfg)
    
    
    # print(pixiv_get())
    
if __name__ == '__main__': 
    main()