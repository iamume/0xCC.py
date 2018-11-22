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

from itertools import chain

import PIL.Image, PIL.ExifTags

#
# SiteBuilder
#
class SiteBuilder:
    def __init__(self, setting):
        self.setting = setting
        self.upload_entry = set()
        self.dbm = DBManager(
                setting)
                #site_name=setting['site_name'],
                #db_file=setting['db_file'])
        self.im = ImageManager(setting['img_max_length'])
        self.uploader = Uploader(setting)
    
    def build(self):
        src_root = self.setting['src_root']
        cut_ = len(str(pathlib.Path(src_root)))
        ignore_ = tuple(self.setting['ignore_files'])
        files_to_upload = []
        
        # gether files
        everything = map(lambda x:
                            str(x)[cut_:],
                            pathlib.Path(src_root).glob('**/*'))
        files = list(filter(lambda x:
                        not os.path.isdir(src_root + x)
                        and not x.endswith(ignore_),
                        everything))

        # add data of new file
        new_files = list(filter(lambda x:
                            self.dbm.is_new(x),
                            files))
        self.register_to_db(new_files)
        
        # update data of modified file        
        mod_files = list(filter(lambda x:
                            self.dbm.is_modified(x),
                            files))
        self.update_db(mod_files)
        
        # files to be done some process
        jobs = new_files + mod_files 
        
        # make symmetrial dir in output
        self.make_symmetrical_dirs(jobs)    
        
        # txt(srcdir) -> html(outdir)
        files_to_compile = list(filter(lambda x:
                                    x.endswith('.txt'),
                                    jobs))
        files_to_upload += self.txt2html(files_to_compile)
        
        # resize and copy jpg files from secdir to outdir
        jpg_files = list(filter(lambda x:
                                x.endswith(('jpg', '.jpeg')),
                                jobs))
        files_to_upload += self.optimize_jpgs(jpg_files)
        
        # copy misc files from srcdir to outdir
        files_to_copy = filter(lambda x:
                                not (x.endswith('.txt') or
                                 x.endswith(('jpg', 'jpeg'))),
                                jobs)
        files_to_upload += list(self.copy_to_out_dir(files_to_copy))
        
        # list up dirs those need new index
        modified_dirs = list(chain.from_iterable(
                                    map(self.extract_path,
                                    jobs)))
        files_to_upload += list(self.update_indexies(modified_dirs))
        
        files_to_upload = set(files_to_upload)
        # upload them
        self.update_site(files_to_upload)
    
    def register_to_db(self, files):
        for file in files:
            mtime = self.get_mtime(file)
            self.dbm.add_item(file, mtime, mtime)
    
    def update_db(self, files):
        for file in files:
            mtime = self.get_mtime(file)
            self.dbm.update_item(file, mtime)
                
    # make html from text files
    def txt2html(self, files):
        result = []
        for file in files:
            reg_time = self.dbm.get_made_time(file)
            dt_ = datetime.datetime.fromtimestamp(reg_time)
            registered_ = dt_.strftime('%Y/%m/%d')
    
            mod_time = self.dbm.get_modified_time(file)
            dt_ = datetime.datetime.fromtimestamp(mod_time)
            modified_ = dt_.strftime('%Y/%m/%d')
    
            p = Publisher(self.setting['templates']['document'])
            output_file = p.publish(
                src_root = self.setting['src_root'],
                out_root = self.setting['out_root'],
                target_path = file,
                registered_time = registered_,
                modified_time = modified_,
                title_prefix = self.setting['site_name'] + ' - ')
            
            result.append(output_file)
        return result
    
    # shrink too large jpg
    def optimize_jpgs(self, files):
        result = list(filter(lambda x: 
                            self.im.do_resize(
                                self.setting['src_root'] + x,
                                self.setting['out_root'] + x),
                            files))
        return result

    # copy misc files
    def copy_to_out_dir(self, files):
        result = []
        for file in files:
            from_ = file
            if os.path.basename(file)[0] == '_':
                d_ = os.path.dirname(file) + os.sep
                n_ = '.' + os.path.basename[1:]
                to_ = d_ + n_
            else:
                to_ = file
            shutil.copy2(
                self.setting['src_root'] + from_,
                self.setting['out_root'] + to_)
            result.append(to_)
        return result
    
    # generate index file
    def update_indexies(self, files):
        result = []
        for file in files:
            p = Publisher(self.setting['templates']['index'])
            p.publish(
                src_root = self.setting['src_root'],
                out_root = self.setting['out_root'],
                target_path = file,
                registered_time = '-',
                modified_time = '-',
                title_prefix = self.setting['site_name'] + ' - ')
            result.append(file + os.sep + 'index.html')
        return result
    
    def update_site(self, files):
        for file in files:
            self.uploader.mirroring_file(file)
            
    # list up all paths from root to given path
    def extract_path(self, path):
        path = path.strip(os.sep)
        result = ['']
        tmp = '/'
        for p in path.split(os.sep)[:-1]:
            tmp += p
            result.append(tmp)
            tmp += os.sep
        return result        
    
    def get_mtime(self, path):
        return os.stat(self.setting['src_root'] + path).st_mtime
    
    def make_symmetrical_dirs(self, dirs):
        # make dir in outdir (if its does not exists)
        base_path = self.setting['out_root'] + os.sep
        for d in dirs:
            path_ = d[:d.rfind(os.sep)]
            if not os.path.exists(base_path + path_):
                os.makedirs(base_path + path_)

#
# SQLite3
#
class DBManager:
    def __init__(self, setting):
        self.db_file = setting['db_file']
        self.connection = sqlite3.connect(self.db_file)
        self.cursor = self.connection.cursor()
        self.site_name = setting['site_name']
        self.src_root = setting['src_root']
        try:
            self.cursor.execute(f'CREATE TABLE [{site_name}] (path text, made integer, modified integer);')
        except:
            pass

    def is_new(self, path):
        query = f'SELECT * FROM [{self.site_name}] WHERE path="{path}";'
        self.cursor.execute(query)
        res = self.cursor.fetchall()
        return True if len(res) == 0 else False

    def is_modified(self, path):
        mtime = os.stat(self.src_root + path).st_mtime
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
            result = target_path + os.sep + out_name
        else:
            path_ = out_root + target_path[:-3] + 'html'
            result = target_path[:-3] + 'html'

        with open(path_, mode='w', encoding='utf-8') as fp:
            fp.write(out)
        return result


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
        return True


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
        path_to_item = self.src_root + path + os.sep
        
        folders = sorted(
                    filter(lambda x:
                            os.path.isdir(path_to_item + x),
                            allitems))
        files = sorted(
                    filter(lambda x:
                            os.path.isfile(path_to_item + x),
                            allitems))
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
# txt2html compiler
#
class Node:
    depth = 0
    indent = ' '
    context = None
    child = []
    
    def build_tag(self, tag_name, empty_element=False,
                attributes=None, open=True, close=False):
        if close:
            tag_ = f'</{tag_name}>'
            return tag_
        elif open:
            tag_ = f'<{tag_name}'
            
        if attributes:
            for key, value in attributes.items():
                tag_ += f' {key}="{value}"'
        if empty_element:
            tag_ += ' /'
        tag_ += '>'
        return tag_

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
        c = self.context.counter('AutoToc')
        
        tag_name = f'h{lv}' # h1~h6
        attr = {'id': f'{self.id_prefix}{c:03}'}
        tag = self.build_tag(tag_name=tag_name, attributes=attr)
        self.context.output(tag, newline=True)
        if lv > 1:
            txt = f'<{txt} → #{self.id_prefix}{c:03}>'
            i_ = self.context.indent_str * lv
            tocline_ = f'{i_} - {txt}\n'
            self.context.toc_buffer += tocline_
        self.find_inline_child(txt)
        self.context.output(self.build_tag(tag_name=tag_name, close=True))


class PNode(Node):
    def __init__(self, context):
        self.context = context

    def parse(self):
        txt = self.context.source.pop(0)
        self.context.output(
            self.build_tag(tag_name='p'),
            newline=True)
        self.find_inline_child(txt)
        self.context.output(
            self.build_tag(tag_name='p', close=True))


class ListNode(Node):
    pattern = re.compile('^( *)(-|[0-9]+\.|\+) *(.*)$')
    def __init__(self, context):
        self.context = context

    def parse(self):
        # Detect list type (ul/ol)
        txt = self.context.source[0]
        symbol_ = self.pattern.search(txt).groups()[1]
        tag_name = 'ul' if symbol_ == '-' else 'ol'
        tag = self.build_tag(tag_name)
        self.context.output(tag, newline=True)
        self.context.indent()
        read_ahead = True
        while self.pattern.search(self.context.source[0]):
            grps = self.pattern.search(
                    self.context.source.pop(0)).groups()
            indent, symbol, txt = grps
            depth = len(indent)
            txt = txt.strip()
            li = self.build_tag(tag_name='li')
            self.context.output(
                self.build_tag(tag_name='li'),
                newline=True)
            self.find_inline_child(txt)
            # case0: end of source
            #   -> close LI, get out from loop.
            if len(self.context.source) == 0:
                self.context.output(
                    self.build_tag(
                        tag_name='li',
                        close=True))
                break
            else:
                is_list = self.is_list(self.context.source[0])
                if is_list:
                    depth_ = self.check_indent(self.context.source[0])
            # case1: next line is in same indent
            #   -> just close LI, then continue this loop
            if (is_list and depth_ == depth):
                self.context.output(
                    self.build_tag(
                        tag_name='li',
                        close=True))
                read_ahead = True
                continue
            # case2: next line is more deep indent
            #   -> make ListNode and parse. After that, close LI.
            elif (is_list and depth_ > depth):
                self.context.indent()
                node = ListNode(self.context)
                node.parse()
                self.context.dedent()
                self.context.output(
                    self.build_tag(
                        tag_name='li',
                        close=True),
                    newline=True)
            # case3: next line is not list
            #   -> close LI, then get out from loop
            else:
                self.context.output(
                    self.build_tag(
                        tag_name='li',
                        close=True))
                break
        self.context.dedent()
        self.context.output(
            self.build_tag(tag_name=tag_name, close=True),
            newline=True)

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
        self.context.output(
            self.build_tag(
                tag_name='figure',
                attributes={'class': 'image'}),
            newline=True)
        self.context.indent()
        self.context.output(
            self.build_tag(
                tag_name='img',
                attributes={'src': img_path},
                empty_element=True),
            newline=True)
        if caption:
            self.context.output(
                self.build_tag(tag_name='figcaption'),
                newline=True)
            self.context.indent()
            self.context.output(
                caption,
                newline=True)
            self.context.dedent()
            self.context.output(
                self.build_tag(
                    tag_name='figcaption',
                    close=True),
                newline=True)
        self.context.dedent()
        self.context.output(
            self.build_tag(tag_name='figure', close=True),
            newline=True)


class BlockquoteNode(Node):
    pattern = re.compile('^<from:(.*)$')
    pattern_close = re.compile('^>$')

    def __init__(self, context):
        self.context = context
        if self.context.html[-1].strip() != '':
            self.context.output('', newline=True)

    def parse(self):
        source = self.pattern.search(
            self.context.source.pop(0)).group(1).strip()
        source_is_link = False if source[:4] != 'http' else True
        self.context.output(
            self.build_tag(
                tag_name='figure',
                attributes={'class': 'blockquote'}))
        self.context.indent()
        if source_is_link:
            attr_ = {'cite': f'{source}'}
        else:
            attr_ = None
        self.context.output(
            self.build_tag(
                tag_name='blockquote',
                attributes=attr_),
                newline=True)
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
        self.context.output(
            self.build_tag(tag_name='blockquote',close=True),
            newline=True)
        self.context.output(
            self.build_tag(tag_name='figcaption'),
            newline=True)
        self.context.indent()
        if source_is_link:
            cap = self.build_tag(
                tag_name='a',
                attributes={'href': source})
            cap += f'{source}'
            cap += self.build_tag(
                tag_name='a',
                close=True)
        else:
            cap = source
        self.context.output(cap, newline=True)
        self.context.dedent()
        self.context.output(
            self.build_tag(
                tag_name='figcaption',
                close=True))
        self.context.dedent()
        self.context.output(
            self.build_tag(
                tag_name='figure',
                close=True),
            newline=True)
        if len(self.context.source) != 0:
            self.context.source.pop(0)


class TableNode(Node):
    pattern = re.compile('^ *?(\|([^\|]+\|)+)$')

    def __init__(self, context):
        self.context = context

    def parse(self):
        self.context.output(
            self.build_tag(tag_name='table'),
            newline=True)
        self.context.indent()
        while len(self.context.source) > 0 and self.pattern.search(self.context.source[0]):
            self.context.output(
                self.build_tag(tag_name='tr'),
                newline=True)
            self.context.indent()
            cells = self.context.source.pop(0).split('|')[1:-1]
            self.context.output('', newline=True)
            for c in cells:
                c = c.strip()
                if c.startswith('*') and c.endswith('*'):
                    tag = 'th'
                else:
                    tag = 'td'
                self.context.output(self.build_tag(tag_name=tag))
                self.find_inline_child(c.strip('*'))
                self.context.output(self.build_tag(tag_name=tag, close=True))
            self.context.dedent()
            self.context.output(
                self.build_tag(tag_name='tr', close=True),
                newline=True)
        self.context.dedent()
        self.context.output(
            self.build_tag(tag_name='table', close=True),
            newline=True)


class AnchorNode(Node):
    pattern = re.compile('<(#[a-zA-Z0-9_]+)? ?([^→<>]*) *(→) *([^→<>]+)>')

    def __init__(self, context):
        self.context = context

    def parse(self, text):
        id_, text, symbol, url_ = self.pattern.search(text).groups()
        if text == '':
            text = url_
        text = text.strip()
        tag_name = 'a'
        attr = {'href': url_}
        if url_.startswith('http'):
            attr['class'] = 'external'
        if id_:
            attr['id'] = id_[1:]
        self.context.output(
            self.build_tag(
                tag_name=tag_name,
                attributes=attr))
        self.context.output(text)
        self.context.output(
            self.build_tag(
                tag_name=tag_name,
                close=True))


class IconNode(Node):
    pattern = re.compile('<icon +([^>]+)>')

    def __init__(self, context):
        self.context = context

    def parse(self, text):
        f = self.pattern.search(text).groups()[0]
        path = self.context.icon_path
        tag_name = 'img'
        attr = {'src': f'{path}{f}.png'}
        tag_ = self.build_tag(
                tag_name=tag_name,
                attributes=attr,
                empty_element=True)
        self.context.output(tag_)


class AnnotationNode(Node):
    pattern = re.compile('\(\*\:([^\)]+)\)')
    id_for_symbol = 'mark_'
    id_for_list = 'list_'

    def __init__(self, context):
        self.context = context

    def parse(self, text):
        if self.context.annotation_count == 0:
            self.init_annotation_section()
        self.context.annotation_count += 1
        c = self.context.annotation_count
        # Put the symbol+count on output
        open_ = self.build_tag(
            tag_name='a',
            attributes={
                'href': f'#{self.id_for_list}{c}',
                'id': f'{self.id_for_symbol}{c}',
                'class': 'annotation'
            })
        close_ = self.build_tag(
            tag_name='a',close=True)
        asterisk_ = f'※{c}'
        self.context.output(
            f'{open_}{asterisk_}{close_}')
        # Append list test at the end of source
        add_ = f'- <#{self.id_for_list}{c} {asterisk_} → #{self.id_for_symbol}{c}> '
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
            self.build_tag(
                tag_name='ol',
                attributes={'class': self.crumbs_class}),
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
                
            li_open = self.build_tag(tag_name='li')
            li_close = self.build_tag(tag_name='li', close=True)
            a_open = self.build_tag(
                tag_name='a',
                attributes={'href': anchor_path})
            a_close = self.build_tag(tag_name='a', close=True)
            line_ = li_open + a_open + n + a_close + li_close
            self.context.output(line_, newline=True)
        else:
            # lase LI element
            name_ = (target + p[-1] + os.sep +
                        self.context.name_file)
            if self.context.text:
                title = self.context.source[0][1:].strip()
            elif os.path.exists(name_):
                with open(name_, encoding='utf-8') as fp:
                    title = fp.read().split('\n')[0].strip()
            else:
                title = self.context.path.split('/')[-1]
            li_open = self.build_tag(tag_name='li')
            li_close = self.build_tag(tag_name='li', close=True)
            em_open = self.build_tag(tag_name='em')
            em_close = self.build_tag(tag_name='em', close=True)
            line_ = li_open + em_open + title + em_close + li_close
            self.context.output(line_, newline=True)

        self.context.dedent()
        self.context.output(
            self.build_tag(tag_name='ol', close=True),
            newline=True)


class TocNode(Node):
    def __init__(self, context):
        self.context = context
        pass

    def parse(self):
        self.context.output(
            self.build_tag(
                tag_name='div',
                attributes={'class': 'ToC'}),
            newline=True)
        self.context.indent()
        h2_open = self.build_tag(tag_name='h2')
        h2_close = self.build_tag(tag_name='h2',close=True)
        h2_text = 'Table of Contents' 
        self.context.output(
            h2_open + h2_text + h2_close,
            newline=True)
        node = RootNode(self.context)
        node.parse()
        self.context.dedent()
        self.context.output(
            self.build_tag(tag_name='div', close=True),
            newline=True)


RootNode.child = [HeaderNode, ListNode, ImgNode, BlockquoteNode, TableNode] # or PNode
TableNode.child = [AnchorNode, IconNode]
BlockquoteNode.child = [ListNode, ImgNode] # or PNode
PNode.child = [IconNode, AnnotationNode, AnchorNode] # or CDataNode
HeaderNode.child = [AnchorNode]
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
