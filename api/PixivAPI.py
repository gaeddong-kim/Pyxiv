import os
import json
import urllib
import requests
import logging
import re

from time import sleep
from io import BytesIO
from datetime import datetime, timedelta

from PIL import Image

from selenium import webdriver

_pixiv_root = 'https://www.pixiv.net'
_pixiv_ajax = _pixiv_root + '/ajax'
_pixiv_login = 'https://accounts.pixiv.net/login'
_pixiv_image = 'https://i.pximg.net/img-original/img/'

_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'

logging.basicConfig(filename='.log', level=logging.WARNING)

def get_cookie(username, password):
    options=webdriver.ChromeOptions()
    options.add_argument('headless')
    options.add_argument('window-size=1920x1080')
    options.add_argument('disable-gpu')

    _driver=webdriver.Chrome('./chromedriver.exe', options=options)
    _driver.get(_pixiv_login)

    id_field, pw_field = _driver.find_elements_by_class_name('input-field')
    
    id_field = id_field.find_element_by_tag_name('input')
    pw_field = pw_field.find_element_by_tag_name('input')

    id_field.send_keys(username)
    pw_field.send_keys(password)

    pw_field.send_keys('\n')

    sleep(10)

    cookies = _driver.get_cookies()
    _driver.quit()

    return cookies

def shift_date(date):
    date, timezone = date.split('+')
    # tz_hour, tz_min = timezone.split(':')

    # 타임존은 UTC+09:00 기준이다. 이는 한국과 일본 시간대에 해당한다.
    date = datetime.strptime(date, '%Y-%m-%dT%H:%M:%S')
    date += timedelta(hours=9) # timedelta(hours=int(tz_hour), minutes=int(tz_min))

    return date.strftime('%Y-%m-%d/%H:%M:%S')


class User:
    def __init__(self, **user_dict):
        if user_dict is not None:
            self.id    = int(user_dict['userId'])
            self.name  = user_dict['name']

    def __getitem__(self, item):
        return self.__getattribute__(item)

    def __repr__(self):
        return f'user {self.name} ({self.id})'


class Illust:
    def __init__(self, **illust_dict):
        try:
            self.dict = {
                'id': int(illust_dict['id']),
                'title': illust_dict['title'],
                'author': User(
                    userId=illust_dict['userId'],
                    name=illust_dict['userName']
                ),
                'uploadDate': shift_date(illust_dict['uploadDate']),
                'thumb': illust_dict['urls']['thumb'],
                'ext': illust_dict['urls']['original'].split('.')[-1],
                'pageCount': illust_dict['pageCount']
            }
        except:
            self.dict = {
                'id': int(illust_dict['id']),
                'title': illust_dict['title'],
                'author': User(
                    userId=illust_dict['userId'],
                    name=illust_dict['userName']
                ),
                'uploadDate': illust_dict['createDate'],
                'thumb': illust_dict['url'],
                'ext': illust_dict['url'].split('.')[-1],
                'pageCount': illust_dict['pageCount']
            }
        
        if type(self['id']) != int:
            self['id'] = int(self['id'])

    def __getitem__(self, item):
        return self.dict[item]

    def __getattr__(self, item):
        return self.dict[item]

    def __repr__(self):
        return f'{self.title} ({self.id})'


class PixivAPI:
    '''
    '''

    def __init__(self, cookies: list):
        self.session = requests.Session()

        self.session.headers['User-Agent'] = _user_agent
        self.session.headers['referer'] = _pixiv_root

        if cookies is not None:
            for cookie in cookies:
                self.session.cookies.set(cookie['name'], cookie['value'])

    def _get_response(self, url: str):
        def decorator(func):
            def wrapper(**kwargs):
                req_url = _pixiv_ajax + url % kwargs

                args = re.findall('%\((.+)\).', url)
                for arg in args:
                    kwargs.pop(arg)

                req_url += ('?' + '&'.join('{}={}'.format(*x) for x in kwargs.items()) if kwargs is not None else '')

                res = json.loads(self.session.get(req_url).text)
                
                return func(res)

            return wrapper
        
        return decorator

    def get_user_data(self, user_id:int, **kwargs) -> User: 
        '''
        get detail information about user.

        user_id: id of illust
        '''

        @self._get_response('/user/%(user_id)d')
        def func(res: dict) -> User:
            return User(**res['body'])

        return func(user_id=user_id, **kwargs)

    def get_illust_data(self, illust_id:int, **kwargs) -> Illust:
        '''
        get detail information about illust.

        illust_id: id of illust
        '''

        @self._get_response('/illust/%(illust_id)d')
        def func(res: dict) -> Illust:
            return Illust(**res['body'])
        
        return func(illust_id=illust_id, **kwargs)

    def get_follow_latest(self, **kwargs) -> list:
        '''
        get list of illust that drawn by user you followed.
        '''

        @self._get_response('/follow_latest/illust')
        def func(res: dict) -> list:
            return [Illust(**illust) for illust in res['body']['thumbnails']['illust']]

        return func(**kwargs)

    def get_user_illust_list(self, user_id:int, **kwargs):
        '''
        get list of illust that drawn by user identified as user_id

        user_id: id of user
        '''

        @self._get_response('/user/%(user_id)d/profile/all')
        def func(res):
            return list(res['body']['illusts'].keys())

        return func(user_id=user_id, **kwargs)

    def get_illust_list(self, tag: list = None, **kwargs) -> list:
        '''
        get list of illust that has tags in 'tag'.

        tag: list of keywords to search
        kwargs:
            order: 
                date: order by date, ascending
                date_d: order by date, descending
                popular_d: order by popular
                popular_male_d: order by popular for male
                popular_female_d: order by popular for female
            p: page number
            mode:
                all: default, doesn't filter anything
                safe: filter R-18 artworks.
                r18: filter non R-18 artworks.
        '''

        if 'order' not in kwargs.keys(): kwargs['order'] = 'date_d'
        if kwargs['order'] not in ('date', 'date_d', 'popular_d', 'popular_male_d', 'popular_female_d'):
            raise RuntimeError('Wrong order!')

        tag_string = urllib.parse.quote(' '.join(tag))

        @self._get_response('/search/artworks/%(tags)s')
        def func(res):
            return [Illust(**x) for x in res['body']['illustManga']['data'] if 'id' in x.keys()]

        return func(tags=tag_string, **kwargs)

    def download_illust(
            self, 
            id: int, 
            path: str = None, 
            thumb: bool = False,
            dir_name: str = '(%(id)d) %(title)s', 
            file_name: str = '%(id)d_p%(idx)d.%(ext)s',
            indices: list = None
            ):
        '''
        Download Illust specified by illust_id
        illust_id: id of illust
        path: path that illust will stored
        '''

        illust_dict = self.get_illust_data(illust_id=id)
        page_count = illust_dict['pageCount']
        ext = illust_dict['ext']

        if thumb:
            response = self.session.get(illust_dict['thumb'], stream=True)
            return Image.open(BytesIO(response.content))

        def page_generator():
            def make_url(i):
                date = illust_dict['uploadDate']
                date = date.replace('-', '/').replace(':', '/')

                file = f'/{id}_p{i}.{ext}'

                return _pixiv_image + date + file

            for i in range(page_count):
                yield make_url(i), file_name % { **illust_dict.dict, 'idx': i }, i

        res = []
        for url, name, i in page_generator():
            if (indices is not None) and (i not in indices):
                continue

            response = self.session.get(url, stream=True)
            if response.status_code != 200:
                logging.warning(f'can\'t download file {name} (id={id})!\n')
                continue

            res.append((response.content, name))

        if path is None:
            res = [Image.open(BytesIO(content)) for content, _ in res]
            return res

        else:
            dir_name = dir_name % illust_dict
            for ch in '\\/:*?",<>|':
                dir_name = dir_name.replace(ch, '')

            full_path = os.path.join(path, dir_name)

            if not os.path.isdir(full_path):
                os.mkdir(full_path)

            for content, name in res:
                with open(full_path + '/' + name, 'wb') as f:
                    f.write(content)


if __name__ == "__main__":
    with open('C:\\Users\\user\\Desktop\\cookie.json') as f:
        cookie = json.load(f)
    
    api = PixivAPI(cookies=cookie)
    print(api.get_follow_latest())