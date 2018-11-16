#!python3

#
# 0xCC ver 0.1
#

import datetime
import ftplib
import json
import os
import pathlib
import re
import shutil
import string
import sqlite3
import sys

import PIL.Image, PIL.ExifTags

#
# SiteBuilder
#
class SiteBuilder:
    def __init__(self, setting):
        self.setting = setting

    def build(self):
        dbm = DBManager(
                site_name=self.setting['site_name'],
                db_file=self.setting['db_file'])
        c = Crawler(
              src_root=self.setting['src_root'],
              db_manager=dbm)
        im = ImageManager(self.setting['img_max_length'])
        uploader = Uploader(self.setting)

        files = c.crawl()
        folders = set()
        task = set()
        upload = set()
        # DB
        for f in files:
            # ignore folders
            if os.path.isdir(self.setting['src_root'] + f):
                continue
            # ignore
            elif f.endswith(tuple(self.setting['ignore_files'])):
                continue
            # new file
            elif dbm.is_new(f):
                t_ = self.get_mtime(f)
                dbm.add_item(f, t_, t_)
                task.add(f)
                for p in self.extract_path(f):
                    folders.add(p)
            # modified file
            elif dbm.is_modified(f, self.get_mtime(f)):
                dbm.update_item(f, self.get_mtime(f))
                task.add(f)
                for p in self.extract_path(f):
                    folders.add(p)

        for t in task:
            self.make_equivalent_folder(t)
            # compile txt
            if t.endswith('.txt'):
                made_time = dbm.get_made_time(t)
                ma_ = datetime.datetime.fromtimestamp(made_time)
                made_ = ma_.strftime('%Y/%m/%d')

                modified_time = dbm.get_modified_time(t)
                mo_ = datetime.datetime.fromtimestamp(modified_time)
                modified_ = mo_.strftime('%Y/%m/%d')

                p = Publisher(self.setting['templates']['document'])
                p.publish(
                    src_root = self.setting['src_root'],
                    out_root = self.setting['out_root'],
                    target_path = t,
                    registered_time = made_,
                    modified_time = modified_,
                    title_prefix = self.setting['site_name'] + ' - ')
                upload.add(t[:-3] + 'html')
            else:
                # copy others
                self.make_out_dir(t)
                if t.endswith(('.jpg', '.jpeg')):
                    self.im.do_resize(
                        self.setting['src_root'] + t,
                        self.setting['src_root'] + t)
                else:
                    self.copy_to_out_dir(t)
                    if os.path.basename(t).startswith('_'):
                        dirname = os.path.dirname(t)
                        filename = '.' + os.path.basename(t)[1:]
                        t = dirname + os.sep + filename
                upload.add(t)

        # generate index file
        for f in folders:
            p = Publisher(self.setting['templates']['index'])
            p.publish(
                src_root = self.setting['src_root'],
                out_root = self.setting['out_root'],
                target_path = f,
                registered_time = '-',
                modified_time = '-',
                title_prefix = self.setting['site_name'] + ' - ')
            upload.add(f + '/index.html')

        for item in upload:
            uploader.mirroring_file(item)
            
    def make_out_dir(self, path):
        tmp = self.setting['out_root'] + os.sep
        for folder in path.split('/')[:-1]:
            if not os.path.exists(tmp + folder):
                os.mkdir(tmp + folder)
            tmp += folder + os.sep
            
    def copy_to_out_dir(self, path):
        from_path = path
        if os.path.basename(path)[0] == '_':
            d_ = os.path.dirname(path) + os.sep
            n_ = '.' + os.path.basename[1:]
            to_path = d_ + n_
        else:
            to_path = path
        shutil.copy2(
            self.setting['src_root'] + from_path,
            self.setting['out_root'] + to_path)

    def extract_path(self, path):
        folders = set()
        tmp_f = path
        level = os.path.dirname(tmp_f).count(os.sep)
        
        for i in range(level):
            tmp_f = tmp_f[:tmp_f.rfind(os.sep)]
            folders.add(tmp_f)
        folders.add('/')
        return folders

    def get_mtime(self, path):
        return os.stat(self.setting['src_root'] + path).st_mtime

    def make_equivalent_folder(self, path):
        # make dir in outdir (if its does not exists)
        tmp = self.setting['out_root'] + os.sep
        for p in path.split(os.sep)[:-1]:
            if not os.path.exists(tmp + p):
                os.mkdir(tmp + p)
            tmp += p + os.sep


#
# Crawler
#
class Crawler:
    def __init__(self, src_root, db_manager):
        self.src_root = src_root
        self.db_manager = db_manager

    def crawl(self):
        files = list(pathlib.Path(self.src_root).glob('**/*'))
        cut = len(str(pathlib.Path(self.src_root)))
        return list(map(lambda x: str(x)[cut:], files))


#
# SQLite3
#
class DBManager:
    def __init__(self, site_name, db_file='site_db.sq3'):
        self.db_file = db_file
        self.connection = sqlite3.connect(self.db_file)
        self.cursor = self.connection.cursor()
        self.site_name = site_name
        try:
            self.cursor.execute(f'CREATE TABLE [{site_name}] (path text, made integer, modified integer);')
        except:
            pass

    def is_new(self, path):
        query = f'SELECT * FROM [{self.site_name}] WHERE path="{path}";'
        self.cursor.execute(query)
        res = self.cursor.fetchall()
        return True if len(res) == 0 else False

    def is_modified(self, path, mtime):
        query = f'SELECT * FROM [{self.site_name}] WHERE path="{path}";'
        self.cursor.execute(query)
        res = self.cursor.fetchone()
        last_modified = list(res)[-1]
        if mtime > last_modified:
            return True
        else:
            return False

    def update_item(self, path, mtime):
        query = f'UPDATE [{self.site_name}] SET modified=? WHERE path=?;'
        dat= (mtime, path)
        self.cursor.execute(query, dat)
        self.connection.commit()

    def add_item(self, path, made, modified):
        query = f'INSERT INTO [{self.site_name}] values (?, ?, ?);'
        dat = (path, made, modified)
        self.cursor.execute(query, dat)
        self.connection.commit()

    def get_made_time(self, path):
        query = f'SELECT * FROM [{self.site_name}] WHERE path="{path}";'
        self.cursor.execute(query)
        res = self.cursor.fetchone()
        made_time = list(res)[1]
        return made_time

    def get_modified_time(self, path):
        query = f'SELECT * FROM [{self.site_name}] WHERE path="{path}"'
        self.cursor.execute(query)
        res = self.cursor.fetchone()
        mod_time = list(res)[2]
        return mod_time


#
# Publish html file
#
class Publisher:
    def __init__(self, template_file=None):
        if template_file:
            self.template_file = template_file
        with open(self.template_file, encoding='utf-8') as fp:
            self.template_str = fp.read()

    def publish(self, src_root, out_root, target_path,
        registered_time='1999/01/01', modified_time='1999/01/01',
        title_prefix='', indent_str=' ', indent_level=2):
        if os.path.isfile(src_root + target_path):
            t_ = src_root + target_path
            with open(t_, encoding='utf-8') as fp:
                text = fp.read()
            con = ContextManager(text=text, path=target_path, indent_str=indent_str, indent_level=indent_level)
            out_name = target_path.split('/')[-1][:-3] + '.html'
        else:
            con = ContextManager(path=target_path, indent_str=indent_str, indent_level=indent_level)
            out_name = 'index.html'
        node = RootNode(con)
        node.parse()

        # generate html body
        if len(con.toc_buffer.split('\n')) > 3:
            buf = con.toc_buffer
            toc = ContextManager(text=con.toc_buffer)
            toc.bread = True
            toc_node = TocNode(toc)
            toc_node.parse()
            idx = 0
            for l in con.html:
                if '<h2' in l:
                    break
                idx += 1
            con.html[idx:idx] = toc.html
        body = '\n'.join(con.html)

        # chimera with template
        h1_pattern = re.compile('<h1[^>]*>([^<]+)</h1>')
        title = 'Untitled Document'
        for l in con.html:
            if h1_pattern.search(l):
                title = h1_pattern.search(l).groups()[0].strip()
                break
        t = string.Template(self.template_str)
        d = {
          'title': f'{title_prefix}{title}',
          'body': body,
          'registered': registered_time,
          'modified': modified_time
        }
        out = t.substitute(d)

        # detect output path
        if out_name == 'index.html':
            path_ = out_root + target_path + os.sep + out_name
        else:
            path_ = out_root + target_path[:-3] + 'html'

        with open(path_, mode='w', encoding='utf-8') as fp:
            fp.write(out)


class ImageManager:
    def __init__(self, max_length, quality=80):
        self.max_length = max_length
        self.quality = quality
        
    def get_rotation_info(self):
        try:
            exif = self.img._getexif()
        except :
            return 0
        meta_data = dict()
        for tag_id, value in exif.items():
            tag = PIL.ExifTags.TAGS.get(tag_id, tag_id)
            meta_data[tag] = value
        angle = meta_data['Orientation']
        if angle == 1 or angle == 2:
            rotate = 0
        elif angle ==  8 or angle == 7:
            rotate =  90
        elif angle == 3 or angle == 4:
            rotate = 180
        else:
            rotate = 270
        return rotate

    def decide_output_size(self):
        org_w = self.img.width
        org_h = self.img.height
        
        if org_w < self.max_length and org_h < self.max_length:
            w, h = org_w, org_h
        elif org_w > org_h:
            w = self.max_length
            h = int(org_h * w / org_w)
        else:
            h = self.max_length
            w = int(org_w * h / org_h)
        return (w, h)
        
    def decide_tmp_size(self):
        org_w = self.img.width
        org_h = self.img.height
        
        # decide output size from size of original image
        if org_w < self.max_length and org_h < self.max_length:
            return False
        elif org_w > org_h:
            h = int(org_h * self.max_length / org_w + 2)
            w = int(org_w * h / org_h)
        else:
            h = self.max_length
            w = int(org_w * self.max_length / org_h + 2)
            h = int(org_h * w / org_w)
        return (w, h)
        
    def do_resize(self, org_path, out_path):
        self.img = PIL.Image.open(org_path)
        r = self.get_rotation_info()
        output_size = self.decide_output_size()
        tmp_size = self.decide_tmp_size()
        if r > 0:
            self.img = self.img.rotate(r, expand=True)
        if r == 90 or r == 270:
            tmp_size = (tmp_size[1], tmp_size[0])
            output_size = (output_size[1], output_size[0])
        if tmp_size:
            self.img = self.img.resize(tmp_size, PIL.Image.LANCZOS)
        if output_size:
            if not tmp_size:
                tmp_size = output_size
            x1 = int((tmp_size[0] - output_size[0]) / 2)
            y1 = int((tmp_size[1] - output_size[1]) / 2)
            x2 = x1 + output_size[0]
            y2 = y1 + output_size[1]
            self.img = self.img.crop((x1, y1, x2, y2))
        with PIL.Image.new(self.img.mode, self.img.size) as out_img:
            out_img.putdata(self.img.getdata())
            out_img.save(out_path)


#
# Upload files via FTP
#
class Uploader:
    ascii_ext = ('css', 'html', 'js', 'txt', 'py', 'md', 'htaccess')
    binary_ext = ('zip', 'jpg', 'jpeg', 'png', 'gif', )

    def __init__(self, setting):
        self.setting = setting
        self.ftp = ftplib.FTP()
        self.ftp.connect(
            host=setting['server_info']['address'],
            port=setting['server_info']['port'])
        self.ftp.login(
            user=setting['server_info']['username'],
            passwd=setting['server_info']['password'])
        self.ftp.cwd(setting['server_info']['working_directory'])

    def mirroring_file(self, target):
        path = target.split('/')
        for folder in path[:-1]:
            flag_ = False
            if folder == '':
                continue
            for item, info in self.ftp.mlsd('.'):
                if item == folder and info['type'] == 'dir':
                    flag_ = True
                    break
            if not flag_:
                self.ftp.mkd(folder)
                self.ftp.sendcmd(f'SITE CHMOD 755 {folder}')
            self.ftp.cwd(folder)
        #self.ftp.cwd(self.setting['server_info']['working_directory'])
        f = target.split('/')[-1]
        if target.endswith(self.ascii_ext):
            with open(self.setting['out_root'] + target, mode='rb') as fp:
                self.ftp.storlines(f'STOR {f}', fp)
        elif target.endswith(self.binary_ext):
            with open(self.setting['out_root'] + target, mode='rb') as fp:
                self.ftp.storbinary(f'STOR {f}', fp)
        else:
            with open(self.setting['out_root'] + target, mode='rb') as fp:
                self.ftp.storbinary(f'STOR {f}', fp)
        self.ftp.sendcmd(f'SITE CHMOD 644 {f}')
        self.ftp.cwd(self.setting['server_info']['working_directory'])


#
# read and write something.
#
class ContextManager:
    #source = []
    #html = ['']
    indent_level = 0
    indent_str = ' '
    #counter_dict = dict()
    src_root = './src'
    out_root = './out'
    name_file = '_name'
    timestamp_format = '%Y/%m/%d'
    icon_path = '/res/icon/'
    #annotation_count = 0
    #toc_buffer = ''

    def __init__(
        self, text=None, path=None, src=None, out=None,
        indent_level=0, indent_str=' '):
        self.bread = False
        self.html = ['']
        self.path = path
        if text:
            self.text = text
            self.source = text.split('\n')
        else:
            self.text = None
            self.source = self.generate_hoax_index(path)
        self.indent_level = indent_level
        self.indent_str = indent_str
        self.counter_dict = dict()
        self.annotation_count = 0
        self.toc_buffer = ''
        if src:
            self.src_root = src
        if out:
            self.out_root = out

    def output(self, text, newline=False):
        if newline:
            self.html.append(self.indent_str * self.indent_level)
        self.html[-1] += text

    def indent(self):
        self.indent_level += 1

    def dedent(self):
        self.indent_level -= 1

    def counter(self, key):
        if key in self.counter_dict:
            self.counter_dict[key] += 1
        else:
            self.counter_dict[key] = 1
        return self.counter_dict[key]

    def generate_hoax_index(self, path):
        if path == None:
            path = '/'
        allitems = os.listdir(self.src_root + path)
        folders = []
        files = []
        for item in allitems:
            if os.path.isdir(self.src_root + path + os.sep + item):
                folders.append(item)
            else:
                files.append(item)
        folders.sort()
        files.sort()
        s = []
        p = self.path if self.path != '/' else ''
        s.append(f'# Index of {p}{os.sep}')
        s.append('|*Name (or title)*|*Last modified*|*Size*|')

        for f in folders:
            t_ = os.sep.join([path, f, self.name_file])
            n = self.src_root + t_
            if os.path.exists(n):
                with open(n, encoding='utf-8') as fp:
                    title = fp.read().split('\n')[0].strip()
            else:
                title = f
            lm = self.mtime_(self.src_root + path + os.sep + f)
            s.append(f'|<icon folder> <{title} → ./{f}>|{lm}|-|')

        for f in files:
            if f == self.name_file:
                continue
            if len(f) > 4 and f[-4:] == '.txt':
                title = f[:-4] + '.html'
                target_ = self.src_root + path + os.sep + f
                with open(target_, encoding='utf-8') as fp:
                    lines = fp.read().split('\n')
                for l in lines:
                    if HeaderNode.pattern.search(l):
                        match_ = HeaderNode.pattern.search(l)
                        title = match_.groups()[1]
                        break
            else:
                title = f
            if f.endswith('.txt'):
                size = self.size_(self.out_root + path + os.sep + f[:-3] + 'html')
            else:
                size = self.size_(self.out_root + path + os.sep + f)
            lm = self.mtime_(self.src_root + path + os.sep + f)
            url = f[:-3] + 'html' if f[-4:] == '.txt' else f
            ext = os.path.splitext(url)[-1][1:]
            s.append(f'|<icon {ext}> <{title} → ./{url}>|{lm}|{size}|')
        return s

    def mtime_(self, path):
        mtime = os.stat(path).st_mtime
        dt = datetime.datetime.fromtimestamp(mtime)
        return dt.strftime(self.timestamp_format)

    def size_(self, path):
        byte = os.path.getsize(path)
        KB = round(byte / 1024, 3)
        return str(KB) + 'KB'


#
# txt2html compiler "TACHYON"
#
class Node:
    depth = 0
    indent = ' '
    context = None
    child = []

    def find_inline_child(self, txt):
        for c in self.child:
            found = c.pattern.search(txt)
            if found:
                pos_start, pos_end = found.span()
                self.find_inline_child(txt[:pos_start])
                node = c(self.context)
                node.parse(txt[pos_start:pos_end])
                self.find_inline_child(txt[pos_end:])
                break
        else:
            node = CDataNode(self.context)
            node.parse(txt)


class RootNode:
    def __init__(self, context):
        self.context = context

    def parse(self):
        if self.context.bread:
            pass
        elif self.context.path:
            node = BreadCrumbNode(self.context)
            node.parse()
        else:
            self.context.path = ''
            node = BreadCrumbNode(self.context)
            node.parse()

        while len(self.context.source) > 0:
            line = self.context.source[0]
            if len(line) == 0:
                self.context.source.pop(0)
                continue

            for c in self.child:
                if c.pattern.search(line) != None:
                    node = c(self.context)
                    break
            else:
                node = PNode(self.context)
            node.parse()


class CDataNode(Node):
    def __init__(self, context):
        self.context = context

    def parse(self, txt):
        self.context.output(txt)


class HeaderNode(Node):
    pattern = re.compile('^([\#]{1,6}) *(.*$)')
    id_prefix = 'AutoToC_'

    def __init__(self, context):
        self.context = context

    def parse(self):
        line = self.context.source.pop(0)
        symbol, txt = self.pattern.search(line).groups()
        lv = len(symbol)
        tag = f'h{lv}' # h1~h6
        c = self.context.counter('AutoToc')
        self.context.output(f'<{tag} id="{self.id_prefix}{c:03}">', newline=True)
        if lv > 1:
            self.context.output(f'<a href="#{self.id_prefix}{c:03}">')
        self.find_inline_child(txt)
        if lv > 1:
            self.context.output('</a>')
        self.context.output(f'</{tag}>')
        if lv > 1:
            indent_ = self.context.indent_str * lv
            self.context.toc_buffer += f'{indent_} - <{txt} → #{self.id_prefix}{c:03}>\n'


class PNode(Node):
    def __init__(self, context):
        self.context = context

    def parse(self):
        txt = self.context.source.pop(0)
        self.context.output('<p>', newline=True)
        self.find_inline_child(txt)
        self.context.output('</p>')


class ListNode(Node):
    pattern = re.compile('^( *)(-|[0-9]+\.|\+) *(.*)$')
    def __init__(self, context):
        self.context = context

    def parse(self):
        # Detect list type (ul/ol)
        txt = self.context.source[0]
        tag = 'ul' if self.pattern.search(txt).groups()[1] == '-' else 'ol'
        self.context.output(f'<{tag}>', newline=True)
        self.context.indent()
        read_ahead = True
        while self.pattern.search(self.context.source[0]):
            indent, symbol, txt = self.pattern.search(self.context.source.pop(0)).groups()
            depth = len(indent)
            txt = txt.strip()
            self.context.output('<li>', newline=True)
            self.find_inline_child(txt)
            # case0: end of source
            #   -> close LI, get out from loop.
            if len(self.context.source) == 0:
                self.context.output('</li>')
                break
            # case1: next line is in same indent
            #   -> just close LI, then continue this loop
            if self.is_list(self.context.source[0]) and self.check_indent(self.context.source[0]) == depth:
                self.context.output('</li>')
                read_ahead = True
                continue
            # case2: next line is more deep indent
            #   -> make ListNode and parse. After that, close LI.
            elif self.is_list(self.context.source[0]) and self.check_indent(self.context.source[0]) > depth:
                self.context.indent()
                node = ListNode(self.context)
                node.parse()
                self.context.dedent()
                self.context.output('</li>', newline=True)
            # case3: next line is not list
            #   -> close LI, then get out from loop
            else:
                self.context.output('</li>')
                break
        self.context.dedent()
        self.context.output(f'</{tag}>', newline=True)

    def is_list(self, text):
        return self.pattern.match(text)

    def check_indent(self, text):
        return len(self.pattern.search(text).groups()[0])


class ImgNode(Node):
    pattern = re.compile('^img:([^\(]*)(\((.*)\))?$')

    def __init__(self, context):
        self.context = context
        if self.context.html[-1].strip() != '':
            self.context.output('', newline=True)

    def parse(self):
        line = self.context.source.pop(0)
        img_path, s, caption = self.pattern.search(line).groups()
        self.context.output('<figure class="image">', newline=True)
        self.context.indent()
        self.context.output(f'<img src="{img_path}" />', newline=True)
        if caption:
            self.context.output('<figcaption>', newline=True)
            self.context.indent()
            self.context.output(caption, newline=True)
            self.context.dedent()
            self.context.output('</figcaption>', newline=True)
        self.context.dedent()
        self.context.output('</figure>', newline=True)


class BlockquoteNode(Node):
    pattern = re.compile('^<from:(.*)$')
    pattern_close = re.compile('^>$')

    def __init__(self, context):
        self.context = context
        if self.context.html[-1].strip() != '':
            self.context.output('', newline=True)

    def parse(self):
        source = self.pattern.search(self.context.source.pop(0)).group(1).strip()
        source_is_link = False if source[:4] != 'http' else True
        self.context.output('<figure class="blockquote">', newline=True)
        self.context.indent()
        self.context.output('<blockquote', newline=True)
        if source_is_link:
            self.context.output(f' cite="{source}">')
        else:
            self.context.output('>')
        self.context.indent()

        while True:
            if len(self.context.source) == 0 or self.pattern_close.search(self.context.source[0]):
                break
            if len(self.context.source[0]) == 0:
                self.context.source.pop()
                continue

            for c in self.child:
                if c.pattern.search(self.context.source[0]) != None:
                    node = c(self.context)
                    break
            else:
                node = PNode(self.context)
            node.parse()

        self.context.dedent()
        self.context.output('</blockquote>', newline=True)
        self.context.output('<figcaption>', newline=True)
        self.context.indent()
        if source_is_link:
            cap = f'<a href="{source}">{source}</a>'
        else:
            cap = source
        self.context.output(cap, newline=True)
        self.context.dedent()
        self.context.output('</figcaption>', newline=True)
        self.context.dedent()
        self.context.output('</figure>', newline=True)
        if len(self.context.source) != 0:
            self.context.source.pop(0)


class TableNode(Node):
    pattern = re.compile('^ *?(\|([^\|]+\|)+)$')

    def __init__(self, context):
        self.context = context

    def parse(self):
        self.context.output('<table>', newline=True)
        self.context.indent()
        while len(self.context.source) > 0 and self.pattern.search(self.context.source[0]):
            self.context.output('<tr>', newline=True)
            self.context.indent()
            cells = self.context.source.pop(0).split('|')[1:-1]
            self.context.output('', newline=True)
            for c in cells:
                c = c.strip()
                if c.startswith('*') and c.endswith('*'):
                    tag = 'th'
                else:
                    tag = 'td'
                self.context.output(f'<{tag}>')
                self.find_inline_child(c.strip('*'))
                self.context.output(f'</{tag}>')
            self.context.dedent()
            self.context.output('</rt>', newline=True)
        self.context.dedent()
        self.context.output('</table>', newline=True)


class AnchorNode(Node):
    pattern = re.compile('<(#[a-zA-Z0-9_]+)? ?([^→<>]*) *(→) *([^→<>]+)>')

    def __init__(self, context):
        self.context = context

    def parse(self, text):
        id_, text, symbol, url_ = self.pattern.search(text).groups()
        if text == '':
            text = url_
        text = text.strip()
        self.context.output(f'<a href="{url_}"')
        if url_.startswith('http'):
            self.context.output(' class="external"')
        if id_:
            self.context.output(f' id="{id_[1:]}"')
        self.context.output('>')
        self.context.output(f'{text}</a>')


class IconNode(Node):
    pattern = re.compile('<icon +([^>]+)>')

    def __init__(self, context):
        self.context = context

    def parse(self, text):
        f = self.pattern.search(text).groups()[0]
        path = self.context.icon_path
        self.context.output(f'<img src="{path}{f}.png" />')


class AnnotationNode(Node):
    pattern = re.compile('\(\*\:([^\)]+)\)')
    id_for_symbol = 'mark_'
    id_for_lsit = 'list_'

    def __init__(self, context):
        self.context = context

    def parse(self, text):
        if self.context.annotation_count == 0:
            self.init_annotation_section()
        self.context.annotation_count += 1
        c = self.context.annotation_count
        # Put the symbol+count on output
        href_ = f'href="#{self.id_for_lsit}{c}"'
        id_ = f'id="{self.id_for_symbol}{c}"'
        class_ = 'class="annotation"'
        self.context.output(
            f'<a {class_} {id_} {href_}">※{c}</a>')
        # Append list test at the end of source
        add_ = f'- <#{href_} ※{c} → #{id_}> '
        add_ += self.pattern.search(text).groups()[0]
        self.context.source.append(add_)

    def init_annotation_section(self):
        self.context.source.append('## notes')


class BreadCrumbNode(Node):
    crumbs_class = 'breadcrumbs'

    def __init__(self, context):
        self.context = context
        pass

    def parse(self):
        #
        # This method may need to be rewriten.
        #
        self.context.output(
            f'<ol class="{self.crumbs_class}">',
            newline=True)
        self.context.indent()
        anchor_path = ''
        target = ''
        if self.context.path == '/':
            p = ['/']
        else:
            p = self.context.path.split(os.sep)
        target = self.context.src_root + os.sep
        for i in range(len(p) - 1):
            if p[i] == '':
                anchor_path ='/'
            else:
                target += p[i] + os.sep
                anchor_path += p[i] + '/'
            
            name_ = target + self.context.name_file
            if os.path.exists(name_):
                with open(name_, encoding='utf-8') as fp:
                    n = fp.read().split('\n')[0].strip()
            else:
                n = p[i]

            self.context.output(
                f'<li><a href="{anchor_path}">{n}</a></li>',
                newline=True)
        else:
            name_ = (target + p[-1] + os.sep +
                        self.context.name_file)
            if self.context.text:
                title = self.context.source[0][1:].strip()
            elif os.path.exists(name_):
                with open(name_, encoding='utf-8') as fp:
                    title = fp.read().split('\n')[0].strip()
            else:
                title = self.context.path.split('/')[-1]
            self.context.output(
                f'<li><em>{title}</em></li>',
                newline=True)

        self.context.dedent()
        self.context.output('</ol>', newline=True)


class TocNode(Node):
    def __init__(self, context):
        self.context = context
        pass

    def parse(self):
        self.context.output('<div class="ToC">', newline=True)
        self.context.indent()
        self.context.output('<h2>Table of Contents</h2>', newline=True)
        node = RootNode(self.context)
        node.parse()
        self.context.dedent()
        self.context.output('</div>', newline=True)


RootNode.child = [HeaderNode, ListNode, ImgNode, BlockquoteNode, TableNode] # or PNode
TableNode.child = [AnchorNode, IconNode]
BlockquoteNode.child = [ListNode, ImgNode] # or PNode
PNode.child = [IconNode, AnnotationNode, AnchorNode] # or CDataNode
HeaderNode.child = [] # or CDataNode
ListNode.child = [AnchorNode, IconNode] # or CDataNode


if __name__ == '__main__':
    myname_ = os.path.basename(__file__)
    
    # get given setting_file. if not given,
    # 'setting.json' will be used.
    for arg in sys.argv:
        if not arg.endswith(myname_):
            file_ = arg
            break
    else:
        file_ = 'setting.json'
    
    with open(file_) as fp:
        json_ = fp.read()
    setting = json.loads(json_)
    sb = SiteBuilder(setting)
    sb.build()

