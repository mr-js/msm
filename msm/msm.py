from flask import Flask, render_template, request, jsonify
import os, stat, platform, subprocess
from datetime import datetime
import shutil
import zipfile
import pathlib
import configparser
from secrets import token_hex
from waitress import serve
import webbrowser
import time
import chardet


class Workspace:
    def __init__(self, name, source_path, destination_path):
        self.name = name
        self.source_path = source_path
        self.destination_path = destination_path
        self.source_files = []
        self.destination_files = []
        self.archive_name = ''
        self.update()

    def __remove_readonly(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def exlore(self, path_type = 'source'):
        match (path_type):
            case 'source':
                path = self.source_path
            case 'archive':
                path = self.destination_path            
            case _:
                path = ''
        if path:
            try:
                match (platform.system()):
                    case 'Windows':
                        os.startfile(path)
                    case 'Darwin':  # macOS
                        subprocess.run(['open', path])
                    case 'Linux':
                        subprocess.run(['xdg-open', path])
                    case _:
                        raise OSError('Unsupported operating system')
                result = True
            except:
                result = False
        return path, result

    def update(self, name_filter=''):
        if os.path.isdir(self.source_path):
            self.source_files = os.listdir(self.source_path)
        if os.path.isdir(self.destination_path):
            self.destination_files = list(map(lambda x: os.path.basename(x), sorted(filter(os.path.isfile, map(lambda x: os.path.join(self.destination_path, x), os.listdir(self.destination_path))), key=os.path.getmtime, reverse=True)))
            if name_filter:
                self.destination_files = list(filter(lambda x: name_filter.lower() in x.lower(), self.destination_files))
        self.archive_name = f'{datetime.now().strftime("%Y%m%d%H%M%S")}.zip'

    def archive_get(self, name):
        return list(filter(lambda workspace: workspace.name == name, self.workspaces))[0]

    def archive_info(self, archive_name):
        archive_filename = os.path.join(self.destination_path, archive_name)
        try:
            archive_datetime = ''
            archive_datetime = datetime.fromtimestamp(os.path.getmtime(archive_filename)).strftime("%Y.%m.%d %H:%M:%S")
        except:
            pass
        try:
            archive_comment = ''
            with zipfile.ZipFile(archive_filename, mode='r') as f:
                comment = f.comment
                encoding = chardet.detect(comment)['encoding']
                archive_comment = comment.decode(encoding)             
        except:
            pass
        try:
            archive_files_counter = 0
            archive_size_compressed = 0
            archive_size_uncompressed = 0
            with zipfile.ZipFile(archive_filename, mode='r') as f:
                for info in f.infolist():
                    archive_files_counter += 1
                    archive_size_compressed += info.compress_size
                    archive_size_uncompressed += info.file_size

            archive_size_compressed = round(archive_size_compressed / (1024 * 1024), 1)
            archive_size_uncompressed = round(archive_size_uncompressed / (1024 * 1024), 1)
        except:
            pass        
        try:
            archive_files = {}
            with zipfile.ZipFile(archive_filename, mode='r') as f:
                files = [info.filename for info in f.infolist()]
            archive_files = ', '.join(file for file in files)
        except:
            pass
        self.update()
        return archive_name, archive_comment, archive_datetime, archive_size_compressed, archive_size_uncompressed, archive_files, archive_files_counter

    def archive_create(self, archive_name, archive_comment=''):
        archive_filename = os.path.join(self.destination_path, archive_name)
        try:
            with zipfile.ZipFile(archive_filename, mode='w', compression=zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=5) as f:
                if len(archive_comment) > 0:
                    archive_comment = archive_comment[0:archive_comment.find(80*'-')-1] if archive_comment.find(80*'-') > 0 else archive_comment
                    f.comment = archive_comment.encode('utf-8')
                directory = pathlib.Path(self.source_path)
                for filename in directory.rglob("*"):
                    f.write(filename, arcname=filename.relative_to(directory))
            self.update()
            return archive_name
        except:
            return ''            
        
    def archive_extract(self, archive_name):
        archive_filename = os.path.join(self.destination_path, archive_name)
        try:
            if os.path.isdir(self.source_path):
                shutil.rmtree(self.source_path, onerror=self.__remove_readonly)
            os.makedirs(self.source_path)
            archive_comment = ''
            with zipfile.ZipFile(archive_filename, 'r') as f:
                f.extractall(self.source_path)
                for file_info in f.infolist():
                    extracted_file_path = os.path.join(self.source_path, file_info.filename)
                    date_time = datetime(*file_info.date_time)
                    timestamp = time.mktime(date_time.timetuple())
                    os.utime(extracted_file_path, (timestamp, timestamp))
                if len(f.comment) > 0:
                    archive_comment = f.comment.decode('utf-8')
            self.update()
            return archive_name
        except:
            return ''
        
    def clear_backups(self):
        try:
            for file in self.destination_files:
                if file.startswith('_') and file.endswith('(BACKUP).zip'):
                    os.remove(os.path.join(self.destination_path, file))
            self.update()
            return 'OK'
        except:
            return ''


class Workspaces:
    workspaces = []
    active_workspace = None

    def __init__(self):
        self.workspaces_reload()

    def __config__read(self, filename='msm.ini'):
        config = configparser.RawConfigParser(dict_type=dict)
        config.optionxform = str
        config.read(filename)
        return config
    
    def __config__write(self, filename='msm.ini'):
        config = configparser.RawConfigParser(dict_type=dict)
        config.optionxform = str
        config['WORKSPACES'] = {}
        for item in self.workspaces:
            config['WORKSPACES'][item.name] = f'{item.source_path} => {item.destination_path}'
        config['COMMON'] = {}
        config['COMMON']['LastGame'] = self.active_workspace.name
        with open(filename, 'w') as configfile:
            config.write(configfile)

    def workspaces_reload(self, filename='msm.ini'):
        config = self.__config__read()
        self.workspaces = []
        for item in config['WORKSPACES']:
            self.workspaces.append(Workspace(name=item, source_path=config['WORKSPACES'].get(item).split('=>')[0].strip(), destination_path=config['WORKSPACES'].get(item).split('=>')[1].strip()))
        self.active_workspace = list(filter(lambda workspace: workspace.name == config['COMMON']['LastGame'], self.workspaces))[0]

    def select_workspace(self, name):
        self.workspaces_reload()
        self.active_workspace = list(filter(lambda workspace: workspace.name == name, self.workspaces))[0]
        self.active_workspace.update()
        self.__config__write()


app = Flask(__name__)
app.secret_key = token_hex(16)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
app.config['MAX_FORM_PARTS'] = 1024 * 1024
app.config['MAX_FORM_MEMORY_SIZE'] = 1024 * 1024
workspaces = Workspaces()


@app.route('/', methods=['POST', 'GET'])
def main():
    global workspaces
    workspaces.active_workspace.update()
    data = {}
    data['message'] = None
    data['archive_name'] = workspaces.active_workspace.archive_name
    data['comment'] = ''
    if request.method == 'POST':
        match request.form['action']:
            case 'Switch':
                workspaces.select_workspace(request.form.get('workspace'))
                data['archive_name'] = workspaces.active_workspace.archive_name
                data['message'] =  f'Workspace {workspaces.active_workspace.name} selected'
            case 'Archive':
                result = workspaces.active_workspace.archive_create(request.form.get('archive_name'), request.form.get('comment'))
                data['message'] =  f'Created archive {result}' if len(result) > 0 else f'Creation ERROR'
            case 'Rollback':
                result = workspaces.active_workspace.archive_create(f'_{datetime.now().strftime("%Y%m%d%H%M%S")} (BACKUP).zip', 'BACKUP')
                data['message'] =  f'Backuped archive {result}' if len(result) > 0 else f'Backuped ERROR'                
                result = workspaces.active_workspace.archive_extract(request.form.get('archive_name'))
                data['message'] =  f'Extracted archive {result}' if len(result) > 0 else f'Extraction ERROR'
            case 'Clear Backups':
                result = workspaces.active_workspace.clear_backups()
                data['message'] =  f'Cleared backups {result}' if len(result) > 0 else f'Cleared ERROR'
            case _:
                ...
    data['archive_filter'] = ''
    data['workspaces'] = workspaces
    data['workspace'] = workspaces.active_workspace
    return render_template('main.html', **data)


@app.route('/destination_files_callback')
def destination_files_callback():
    archive_name = request.args.get('archive_name', '', type=str)
    archive_name, archive_comment, archive_datetime, archive_size_compressed, archive_size_uncompressed, archive_files, archive_files_counter = workspaces.active_workspace.archive_info(archive_name)
    # archive_files_formatted = '\n'.join(f'{v}\t{k}' for k, v in archive_files.items())
    archive_files_formatted = archive_files
    result = f'{archive_comment}\n{80*"-"}\nDATE:\t{archive_datetime}\tFILES:\t{archive_files_counter}\tSIZE:\t{archive_size_compressed}/{archive_size_uncompressed} MB\n{80*"-"}\n{archive_files_formatted}'
    return jsonify(result=result)


@app.route('/archive_filter_callback')
def archive_filter_callback():
    global workspaces 
    archive_filter = request.args.get('archive_filter', '', type=str)
    workspaces.active_workspace.update(archive_filter)
    return jsonify(result=workspaces.active_workspace.destination_files)


@app.route('/source_files_callback')
def source_files_callback():
    source_name = request.args.get('source_name', '', type=str)
    source_path = workspaces.active_workspace.source_path
    source_filename = os.path.join(source_path, source_name)
    source_datetime = datetime.fromtimestamp(os.path.getmtime(source_filename)).strftime("%Y.%m.%d %H:%M:%S")
    result = f'{source_name}\n{80*"-"}\nCREATION TIME:\t{source_datetime}\tFILE PATH:\n{80*"-"}\n{source_path}'
    return jsonify(result=result)


@app.route('/explore_callback')
def explore_callback():
    path_type = request.args.get('path_type', '', type=str)
    path, result =  workspaces.active_workspace.exlore(path_type)
    result = f'Explored "{path}"' if result else f'Cannot explore "{path}"'
    return jsonify(result=result)


if __name__ == '__main__':
    if app.debug:
        if not os.environ.get("WERKZEUG_RUN_MAIN"):
            webbrowser.open('http://127.0.0.1:5000')
        app.run(host='0.0.0.0', debug=True, port='5000')
    else:
        port = 10911
        webbrowser.open(f'http://127.0.0.1:{port}')
        serve(app, host="0.0.0.0", port=port)
