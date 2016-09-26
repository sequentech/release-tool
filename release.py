 #!/usr/bin/python

# This file is part of agora-release.
# Copyright (C) 2016  Agora Voting SL <agora@agoravoting.com>

# agora-release is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License.

# agora-release  is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with agora-release.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import re

def print_help():
    print('''
          Usage: release.py [path] [version]
          ''' )

def read_text_file(file_path):
    textfile = open(file_path, "r")
    text = textfile.read()
    textfile.close()
    return text

def write_text_file(file_path, text):
    textfile = open(file_path, "w")
    textfile.write(text)
    textfile.close()

def get_project_type(dir_path):
    config_file = read_text_file(dir_path + "/.git/config")
    my_match = re.search('url\s*=\s*git@github.com:agoravoting/(?P<proj_name>.+)\.git', config_file)

    try:
        my_match.group('proj_name')
    except:
        my_match = re.search('url\s*=\s*https://github.com/agoravoting/(?P<proj_name>.+)\.git', config_file)

    return my_match.group('proj_name')

def do_gui_common(dir_path, version):

    print("avConfig.js...")
    avConfig = read_text_file(dir_path + "/avConfig.js")
    avConfig = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[0-9.]+';", "var AV_CONFIG_VERSION = '" + version + "';", avConfig)
    write_text_file(dir_path + "/avConfig.js", avConfig)

    print("bower.json...")
    bower = read_text_file(dir_path + "/bower.json")
    bower = re.sub('"version"\s*:\s*"[0-9.]+"', '"version" : "'+ version + '"', bower)
    write_text_file(dir_path + "/bower.json", bower)

    print("package.json...")
    package = read_text_file(dir_path + "/package.json")
    package = re.sub('"version"\s*:\s*"[0-9.]+"', '"version" : "'+ version + '"', package)
    write_text_file(dir_path + "/package.json", package)

    print("Gruntfile.js...")
    Gruntfile = read_text_file(dir_path + "/Gruntfile.js")
    Gruntfile = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[0-9.]+';", "var AV_CONFIG_VERSION = '" + version + "';", Gruntfile)
    Gruntfile = re.sub("appCommon-v[0-9.]+\.js", "appCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libCommon-v[0-9.]+\.js", "libCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libnocompat-v[0-9.]+\.js", "libnocompat-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libcompat-v[0-9.]+\.js", "libcompat-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avConfig-v[0-9.]+\.js", "avConfig-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avThemes-v[0-9.]+\.js", "avThemes-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avPlugins-v[0-9.]+\.js", "avPlugins-v" + version + ".js", Gruntfile)
    write_text_file(dir_path + "/Gruntfile.js", Gruntfile)

def do_gui_other(dir_path, version):
    print("index.html...")
    index = read_text_file(dir_path + "/index.html")
    index = re.sub("libnocompat-v[0-9.]+\.js", "libnocompat-v" + version + ".js", index)
    index = re.sub("libcompat-v[0-9.]+\.js", "libcompat-v" + version + ".js", index)
    index = re.sub("avTheme-v[0-9.]+\.js", "avTheme-v" + version + ".js", index)
    index = re.sub("appCommon-v[0-9.]+\.js", "appCommon-v" + version + ".js", index)
    index = re.sub("libCommon-v[0-9.]+\.js", "libCommon-v" + version + ".js", index)
    write_text_file(dir_path + "/index.html", index)

    print("Gruntfile.js...")
    Gruntfile = read_text_file(dir_path + "/Gruntfile.js")
    Gruntfile = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[0-9.]+';", "var AV_CONFIG_VERSION = '" + version + "';", Gruntfile)
    Gruntfile = re.sub("appCommon-v[0-9.]+\.js", "appCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libCommon-v[0-9.]+\.js", "libCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libnocompat-v[0-9.]+\.min\.js", "libnocompat-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("libcompat-v[0-9.]+\.min\.js", "libcompat-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("avConfig-v[0-9.]+\.js", "avConfig-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avThemes-v[0-9.]+\.js", "avThemes-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avPlugins-v[0-9.]+\.js", "avPlugins-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("app-v[0-9.]+\.min\.js", "app-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("lib-v[0-9.]+\.min\.js", "lib-v" + version + ".min.js", Gruntfile)
    write_text_file(dir_path + "/Gruntfile.js", Gruntfile)

    print("bower.json...")
    bower = read_text_file(dir_path + "/bower.json")
    bower = re.sub('"version"\s*:\s*"[0-9.]+"', '"version" : "'+ version + '"', bower)
    write_text_file(dir_path + "/bower.json", bower)

    print("package.json...")
    package = read_text_file(dir_path + "/package.json")
    package = re.sub('"version"\s*:\s*"[0-9.]+"', '"version" : "'+ version + '"', package)
    write_text_file(dir_path + "/package.json", package)

def do_agora_verifier(dir_path, version):
    print("build.sbt...")
    build = read_text_file(dir_path + "/build.sbt")
    build = re.sub('version\s*:=\s*"[0-9.]+"', 'version := "'+ version + '"', build)
    write_text_file(dir_path + "/build.sbt", build)

def do_election_orchestra(dir_path, version):
    print("requirements.txt...")
    requirements = read_text_file(dir_path + "/requirements.txt")
    requirements = re.sub('git\+https://github.com/agoravoting/frestq\.git@.*', 'git+https://github.com/agoravoting/frestq.git@'+ version, requirements)
    write_text_file(dir_path + "/requirements.txt", requirements)

def do_agora_dev_box(dir_path, version):
    print("repos.yml...")
    repos = read_text_file(dir_path + "/repos.yml")
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(dir_path + "/repos.yml", repos)

    print("agora-gui/templates/avConfig.js...")
    Gruntfile = read_text_file(dir_path + "/agora-gui/templates/avConfig.js")
    Gruntfile = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[0-9.]+';", "var AV_CONFIG_VERSION = '" + version + "';", Gruntfile)
    write_text_file(dir_path + "/agora-gui/templates/avConfig.js", Gruntfile)

def do_agora_results(dir_path, version):
    print("setup.py...")
    repos = read_text_file(dir_path + "/setup.py")
    repos = re.sub("version\s*=\s*'[0-9.]+'\s*,", "version='" + version +"',", repos)
    write_text_file(dir_path + "/setup.py", repos)

def main():
    dir_path = os.getcwd()
    version = "1.0.0"

    # read path and version from the arguments
    if 3 == len(sys.argv):
        dir_path = sys.argv[1]
        version = sys.argv[2]

        if len(dir_path) > 1 and '/' == dir_path[-1:]:
            dir_path = dir_path[:-1]

        if not os.path.isdir(dir_path):
            raise Exception(dir_path + ": path does not exist or is not a folder")

        print("dir_path : " + dir_path + " version: " + version)

    else:
        print_help()
        raise SystemExit

    project_type = get_project_type(dir_path)
    print("project: " + project_type)

    if project_type == 'agora-gui-common':
        do_gui_common(dir_path, version)
    elif project_type == 'agora-gui-admin':
        do_gui_other(dir_path, version)
    elif project_type == 'agora-gui-elections':
        do_gui_other(dir_path, version)
    elif project_type == 'agora-gui-booth':
        do_gui_other(dir_path, version)
    elif project_type == 'election-orchestra':
        do_election_orchestra(dir_path, version)
    elif project_type == 'agora-verifier':
        do_agora_verifier(dir_path, version)
    elif project_type == 'agora-dev-box':
        do_agora_dev_box(dir_path, version)
    elif project_type == 'agora-results':
        do_agora_results(dir_path, version)
    elif project_type == 'agora-tally':
        do_agora_results(dir_path, version)
    elif project_type == 'frestq':
        do_agora_results(dir_path, version)

    print("done")

main()











