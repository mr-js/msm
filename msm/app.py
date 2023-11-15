from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from werkzeug.wrappers import Request, Response
from werkzeug.utils import secure_filename
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
import chardet
import configparser
from secrets import token_hex
from waitress import serve
import webbrowser


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


        def update(self):
            if os.path.isdir(self.source_path):
                self.source_files = os.listdir(self.source_path)
            if os.path.isdir(self.destination_path):
                self.destination_files = os.listdir(self.destination_path)
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
                    encoding = chardet.detect(f.comment)['encoding']
                    archive_comment = f.comment.decode(encoding)
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


        def archive_exctract(self, archive_name):
            archive_filename = os.path.join(self.destination_path, archive_name)
            if not os.path.isfile(archive_filename):
                return ''
            if os.path.isdir(self.source_path):
                shutil.rmtree(self.source_path, onerror=self.__remove_readonly)
            os.makedirs(self.source_path)
            archive_comment = ''
            with zipfile.ZipFile(archive_filename, mode='r') as f:
                f.extractall(self.source_path)
                if len(f.comment) > 0:
                    encoding = chardet.detect(f.comment)['encoding']
                    archive_comment = f.comment.decode(encoding)
            self.update()
            return archive_name


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
    request.form.archive_comment = ''
    if request.method == 'POST':
        if request.form['action'] == 'Switch':
            workspaces.select_workspace(request.form.get('workspace'))
            request.form.archive_name = workspaces.active_workspace.archive_name
            message = f'Workspace {workspaces.active_workspace.name} selected'
        elif request.form['action'] == 'Archive':
            result = workspaces.active_workspace.archive_create(request.form.get('archive_name'), request.form.get('archive_comment'))
            message = f'Created archive {result}'
            if len(result) > 0:
                message = f'Created archive {result}'
            else:
                message = f'Creation ERROR'
        elif request.form['action'] == 'Rollback':
            result = workspaces.active_workspace.archive_exctract(request.form.get('archive_name'))
            if len(result) > 0:
                message = f'Extracted archive {result}'
            else:
                message = f'Extraction ERROR'
    else:
        ...
    return render_template('main.html', workspaces=workspaces, workspace=workspaces.active_workspace, message=message)


@app.route('/destination_files_callback')
def destination_files_callback():
    archive_name = request.args.get('archive_name', '', type=str)
    archive_name, archive_comment, archive_datetime, archive_files = workspaces.active_workspace.archive_info(archive_name)
    archive_files_formatted = '\n'.join(f'{v}\t{k}' for k, v in archive_files.items())
    result = f'{archive_comment}\n{61*"-"}\nCREATION TIME:\t{archive_datetime}\tFILES LIST:\n{61*"-"}\n{archive_files_formatted}'
    return jsonify(result=result)


if __name__ == '__main__':
    # app.run(debug=True)
    # run_simple(hostname='localhost', port=9000, application=app, use_reloader=True, use_debugger=True)
    webbrowser.open('http://127.0.0.1:8080')
    serve(app, host="0.0.0.0", port=8080)
