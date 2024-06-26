from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from werkzeug.wrappers import Request, Response
from werkzeug.serving import run_simple
from markupsafe import escape
import os, stat
from dataclasses import dataclass, field
from typing import List
from datetime import datetime
from typing import List
import shutil
import zipfile
import pathlib
import configparser
from secrets import token_hex
from waitress import serve
import webbrowser
import time


@dataclass
class Workspaces:
    @dataclass
    class Workspace:
        name: str = ''
        source_path: str = ''
        destination_path: str = ''
        archive_name: str = ''


        def __remove_readonly(func, path, _):
            os.chmod(path, stat.S_IWRITE)
            func(path)


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
            if not os.path.isfile(archive_filename):
                return '', '', ''
            archive_datetime = datetime.fromtimestamp(os.path.getmtime(archive_filename)).strftime("%Y.%m.%d %H:%M:%S")
            archive_comment = ''
            archive_files = dict()
            with zipfile.ZipFile(archive_filename, mode='r') as f:
                if len(f.comment) > 0:
                    archive_comment = f.comment.decode('utf-8')
                for info in f.infolist():
                    archive_files[info.filename] = datetime(*info.date_time).strftime("%Y.%m.%d %H:%M:%S")
            self.update()
            return archive_name, archive_comment, archive_datetime, archive_files


        def archive_create(self, archive_name, archive_comment=''):
            archive_filename = os.path.join(self.destination_path, archive_name)
            with zipfile.ZipFile(archive_filename, mode='w', compression=zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=5) as f:
                if len(archive_comment) > 0:
                    archive_comment = archive_comment[0:archive_comment.find(61*'-')-1] if archive_comment.find(61*'-') > 0 else archive_comment
                    f.comment = archive_comment.encode('utf-8')
                directory = pathlib.Path(self.source_path)
                for filename in directory.rglob("*"):
                    f.write(filename, arcname=filename.relative_to(directory))
            self.update()
            return archive_name


        def archive_extract(self, archive_name):
            archive_filename = os.path.join(self.destination_path, archive_name)
            if not os.path.isfile(archive_filename):
                return ''
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


        def clear_backups(self):
            for file in self.destination_files:
                if file.startswith('_') and file.endswith('(BACKUP).zip'):
                    os.remove(os.path.join(self.destination_path, file))
            self.update()
            return 'OK'
        

    workspaces: list = field(default_factory=list)
    active_workspace: Workspace = None


    def __init__(self):
        self.workspaces_reload()


    def workspaces_reload(self, filename='msm.ini'):
        config = configparser.RawConfigParser()
        config.read(filename)
        self.workspaces = []
        for item in config['WORKSPACES']:
            self.workspaces.append(self.Workspace(name=item, source_path=config['WORKSPACES'].get(item).split('=>')[0].strip(), destination_path=config['WORKSPACES'].get(item).split('=>')[1].strip()))
        self.active_workspace = self.workspaces[1]


    def select_workspace(self, name):
        self.workspaces_reload()
        self.active_workspace = list(filter(lambda workspace: workspace.name == name, self.workspaces))[0]
        self.active_workspace.update()


app = Flask(__name__)
app.secret_key = token_hex(16)
workspaces = Workspaces()


@app.route('/', methods=['POST', 'GET'])
def main():
    global workspaces
    workspaces.active_workspace.update()
    message = None
    request.form.archive_name = workspaces.active_workspace.archive_name
    request.form.comment = ''
    if request.method == 'POST':
        match request.form['action']:
            case 'Switch':
                workspaces.select_workspace(request.form.get('workspace'))
                request.form.archive_name = workspaces.active_workspace.archive_name
                message = f'Workspace {workspaces.active_workspace.name} selected'
            case 'Archive':
                result = workspaces.active_workspace.archive_create(request.form.get('archive_name'), request.form.get('comment'))
                message = f'Created archive {result}' if len(result) > 0 else f'Creation ERROR'
            case 'Rollback':
                result = workspaces.active_workspace.archive_create(f'_{datetime.now().strftime("%Y%m%d%H%M%S")} (BACKUP).zip', 'BACKUP')
                message = f'Backuped archive {result}' if len(result) > 0 else f'Backuped ERROR'                
                result = workspaces.active_workspace.archive_extract(request.form.get('archive_name'))
                message = f'Extracted archive {result}' if len(result) > 0 else f'Extraction ERROR'
            case 'Clear':
                result = workspaces.active_workspace.clear_backups()
                message = f'Cleared backups {result}' if len(result) > 0 else f'Cleared ERROR'
            case _:
                ...
    request.form.archive_filter = ''
    return render_template('main.html', workspaces=workspaces, workspace=workspaces.active_workspace, message=message)


@app.route('/destination_files_callback')
def destination_files_callback():
    archive_name = request.args.get('archive_name', '', type=str)
    archive_name, archive_comment, archive_datetime, archive_files = workspaces.active_workspace.archive_info(archive_name)
    archive_files_formatted = '\n'.join(f'{v}\t{k}' for k, v in archive_files.items())
    result = f'{archive_comment}\n{61*"-"}\nCREATION TIME:\t{archive_datetime}\tFILES LIST:\n{61*"-"}\n{archive_files_formatted}'
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
    result = f'{source_name}\n{61*"-"}\nCREATION TIME:\t{source_datetime}\tFILE PATH:\n{61*"-"}\n{source_path}'
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
