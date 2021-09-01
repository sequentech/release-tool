#!/usr/bin/env python3

# This file is part of agora-release.
# Copyright (C) 2016-2021 Agora Voting SL <agora@agoravoting.com>

# agora-release is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License.

# agora-release  is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with agora-release.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import subprocess
import os
import re

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
    config_file = read_text_file(os.path.join(dir_path, ".git/config"))
    my_match = re.search('url\s*=\s*git@(github|gitlab).com:(agoravoting|nvotes)/(?P<proj_name>.+)\.git', config_file)

    try:
        my_match.group('proj_name')
    except:
        my_match = re.search('url\s*=\s*https://(github|gitlab).com/(agoravoting|nvotes)/(?P<proj_name>.+)\.git', config_file)

    return my_match.group('proj_name')

def do_gui_common(dir_path, version):

    print("avConfig.js...")
    avConfig = read_text_file(os.path.join(dir_path, "avConfig.js"))
    avConfig = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[^']+';", "var AV_CONFIG_VERSION = '" + version + "';", avConfig)
    write_text_file(os.path.join(dir_path, "avConfig.js"), avConfig)

    print("package.json...")
    package = read_text_file(os.path.join(dir_path, "package.json"))
    package = re.sub('"version"\s*:\s*"[^"]+"', '"version" : "'+ version + '"', package)
    write_text_file(os.path.join(dir_path, "package.json"), package)

    print("Gruntfile.js...")
    Gruntfile = read_text_file(os.path.join(dir_path, "Gruntfile.js"))
    Gruntfile = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[^']+';", "var AV_CONFIG_VERSION = '" + version + "';", Gruntfile)
    Gruntfile = re.sub("appCommon-v[0-9a-zA-Z.\-+]+\.js", "appCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libCommon-v[0-9a-zA-Z.\-+]+\.js", "libCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libnocompat-v[0-9a-zA-Z.\-+]+\.js", "libnocompat-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libcompat-v[0-9a-zA-Z.\-+]+\.js", "libcompat-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avConfig-v[0-9a-zA-Z.\-+]+\.js", "avConfig-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avThemes-v[0-9a-zA-Z.\-+]+\.js", "avThemes-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avPlugins-v[0-9a-zA-Z.\-+]+\.js", "avPlugins-v" + version + ".js", Gruntfile)
    write_text_file(os.path.join(dir_path, "Gruntfile.js"), Gruntfile)

    print("running grunt build..")
    call_process("grunt build", shell=True, cwd=dir_path)

def do_gui_other(dir_path, version):
    print("index.html...")
    index = read_text_file(os.path.join(dir_path, "index.html"))
    index = re.sub("libnocompat-v.*\.js", "libnocompat-v" + version + ".js", index)
    index = re.sub("libcompat-v.*\.js", "libcompat-v" + version + ".js", index)
    index = re.sub("avTheme-v.*\.js", "avTheme-v" + version + ".js", index)
    index = re.sub("appCommon-v.*\.js", "appCommon-v" + version + ".js", index)
    index = re.sub("libCommon-v.*\.js", "libCommon-v" + version + ".js", index)
    write_text_file(os.path.join(dir_path, "index.html"), index)

    print("Gruntfile.js...")
    Gruntfile = read_text_file(os.path.join(dir_path, "Gruntfile.js"))
    Gruntfile = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[^']+';", "var AV_CONFIG_VERSION = '" + version + "';", Gruntfile)
    Gruntfile = re.sub("appCommon-v[0-9a-zA-Z.\-+]+\.js", "appCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libCommon-v[0-9a-zA-Z.\-+]+\.js", "libCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libnocompat-v[0-9a-zA-Z.\-+]+\.min\.js", "libnocompat-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("libcompat-v[0-9a-zA-Z.\-+]+\.min\.js", "libcompat-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("avConfig-v[0-9a-zA-Z.\-+]+\.js", "avConfig-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avThemes-v[0-9a-zA-Z.\-+]+\.js", "avThemes-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("avPlugins-v[0-9a-zA-Z.\-+]+\.js", "avPlugins-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("app-v[0-9a-zA-Z.\-+]+\.min\.js", "app-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("lib-v[0-9a-zA-Z.\-+]+\.min\.js", "lib-v" + version + ".min.js", Gruntfile)
    write_text_file(os.path.join(dir_path, "Gruntfile.js"), Gruntfile)

    print("package.json...")
    package = read_text_file(os.path.join(dir_path, "package.json"))
    package = re.sub('"version"\s*:\s*"[^"]+"', '"version" : "'+ version + '"', package)
    write_text_file(os.path.join(dir_path, "package.json"), package)

def do_agora_elections(dir_path, version):
    print("build.sbt...")
    build = read_text_file(os.path.join(dir_path, "build.sbt"))
    build = re.sub('version\s*:=\s*"[^"]+"', 'version := "'+ version + '"', build)
    write_text_file(os.path.join(dir_path, "build.sbt"), build)

def do_agora_verifier(dir_path, version):
    print("build.sbt...")
    build = read_text_file(os.path.join(dir_path, "build.sbt"))
    build = re.sub('version\s*:=\s*"[^"]+"', 'version := "'+ version + '"', build)
    m = re.search('scalaVersion := "(?P<scalaVersion>[0-9]+\.[0-9]+)\.[0-9]"', build)
    scalaVersion = m.group('scalaVersion')
    print("scalaVersion is " + scalaVersion)
    write_text_file(os.path.join(dir_path, "build.sbt"), build)

    print("package.sh...")
    package = read_text_file(os.path.join(dir_path, "package.sh"))
    package = re.sub('cp target/scala-' + scalaVersion + '/proguard/agora-verifier_' + scalaVersion +  '-[0-9.]+jar dist',
                     'cp target/scala-' + scalaVersion + '/proguard/agora-verifier_' + scalaVersion +  '-' + version + '.jar dist',
                     package)
    write_text_file(os.path.join(dir_path, "package.sh"), package)

    print('pverify.sh..')
    pverify = read_text_file(os.path.join(dir_path, "pverify.sh"))
    pverify = re.sub('java -Djava\.security\.egd=file:/dev/\./urandom -classpath agora-verifier_' + scalaVersion + '-[0-9.]+jar org\.agoravoting\.agora\.Verifier \$1 \$2',
                     'java -Djava.security.egd=file:/dev/./urandom -classpath agora-verifier_' + scalaVersion + '-'  + version + '.jar org.agoravoting.agora.Verifier $1 $2',
                     pverify)
    write_text_file(os.path.join(dir_path, "pverify.sh"), pverify)

    print('vmnc.sh..')
    vmnc = read_text_file(os.path.join(dir_path, "vmnc.sh"))
    vmnc = re.sub('java -Djava.security\.egd=file:/dev/\./urandom -classpath \$DIR/agora-verifier_' + scalaVersion + '-[0-9.]+jar org\.agoravoting\.agora\.Vmnc "\$@"',
                  'java -Djava.security.egd=file:/dev/./urandom -classpath $DIR/agora-verifier_' + scalaVersion + '-' + version + '.jar org.agoravoting.agora.Vmnc "$@"',
                  vmnc)
    write_text_file(os.path.join(dir_path, "vmnc.sh"), vmnc)

    print("project.spdx.yml..")
    spdx = read_text_file(os.path.join(dir_path, "project.spdx.yml"))
    spdx = re.sub(
        "name:\s*\"agora-verifier-[^\"]+\"\s*", 
        "name: \"agora-verifier-" + version +"\"\n", 
        spdx
    )
    spdx = re.sub(
        "  name:\s*\"agora-verifier\"\s*\n  versionInfo:\s*\"[^\"]+\"", 
        f"  name: \"agora-verifier\"\n  versionInfo: \"{version}\"", 
        spdx,
        flags=re.MULTILINE
    )
    spdx = re.sub(
        'downloadLocation: "git\+https://github.com/agoravoting/agora-verifier\.git@.*\"',
        f'downloadLocation: "git+https://github.com/agoravoting/agora-verifier.git@{version}\"',
        spdx
    )
    write_text_file(os.path.join(dir_path, "project.spdx.yml"), spdx)

def do_election_orchestra(dir_path, version):
    print("requirements.txt...")
    requirements = read_text_file(os.path.join(dir_path, "requirements.txt"))
    requirements = re.sub('git\+https://github.com/agoravoting/frestq\.git@.*', 'git+https://github.com/agoravoting/frestq.git@'+ version, requirements)
    write_text_file(os.path.join(dir_path, "requirements.txt"), requirements)

    setup_py = read_text_file(os.path.join(dir_path, "setup.py"))
    setup_py = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", setup_py)
    setup_py = re.sub('git\+https://github.com/agoravoting/frestq\.git@.*', 'git+https://github.com/agoravoting/frestq.git@'+ version, setup_py)
    write_text_file(os.path.join(dir_path, "setup.py"), setup_py)

def do_agora_dev_box(dir_path, version):
    print("repos.yml...")
    repos = read_text_file(os.path.join(dir_path, "repos.yml"))
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(os.path.join(dir_path, "repos.yml"), repos)

    print("config.yml...")
    repos = read_text_file(os.path.join(dir_path, "config.yml"))
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(os.path.join(dir_path, "config.yml"), repos)

    print("doc/devel/agora.config.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/devel/agora.config.yml"))
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(os.path.join(dir_path, "doc/devel/agora.config.yml"), repos)

    print("doc/devel/auth1.config.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/devel/auth1.config.yml"))
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(os.path.join(dir_path, "doc/devel/auth1.config.yml"), repos)

    print("doc/devel/auth2.config.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/devel/auth2.config.yml"))
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(os.path.join(dir_path, "doc/devel/auth2.config.yml"), repos)

    print("doc/production/config.auth.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/production/config.auth.yml"))
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(os.path.join(dir_path, "doc/production/config.auth.yml"), repos)

    print("doc/production/config.master.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/production/config.master.yml"))
    repos = re.sub('version:\s*.*\s*\n', 'version: '+ version + '\n', repos)
    write_text_file(os.path.join(dir_path, "doc/production/config.master.yml"), repos)

    print("helper-tools/config_prod_env.py...")
    helper_script = read_text_file(os.path.join(dir_path, "helper-tools/config_prod_env.py"))
    rx = re.compile("\s*OUTPUT_PROD_VERSION\s*=\s*['|\"]?([0-9a-zA-Z.\-+]*)['|\"]?\s*\n", re.MULTILINE)
    search = rx.search(helper_script)
    old_version = search.group(1)
    helper_script = re.sub("INPUT_PROD_VERSION\s*=\s*['|\"]?[0-9a-zA-Z.\-+]*['|\"]?\s*\n", "INPUT_PROD_VERSION=\""+ old_version + "\"\n", helper_script)
    helper_script = re.sub("INPUT_PRE_VERSION\s*=\s*['|\"]?[0-9a-zA-Z.\-+]*['|\"]?\s*\n", "INPUT_PRE_VERSION=\""+ version + "\"\n", helper_script)
    helper_script = re.sub("OUTPUT_PROD_VERSION\s*=\s*['|\"]?[0-9a-zA-Z.\-+]*['|\"]?\s*\n", "OUTPUT_PROD_VERSION=\""+ version + "\"\n", helper_script)
    write_text_file(os.path.join(dir_path, "helper-tools/config_prod_env.py"), helper_script)

    print("agora-gui/templates/avConfig.js...")
    Gruntfile = read_text_file(os.path.join(dir_path, "agora-gui/templates/avConfig.js"))
    Gruntfile = re.sub("var\s+AV_CONFIG_VERSION\s*=\s*'[^']+';", "var AV_CONFIG_VERSION = '" + version + "';", Gruntfile)
    write_text_file(os.path.join(dir_path, "agora-gui/templates/avConfig.js"), Gruntfile)

def do_agora_results(dir_path, version):
    print("setup.py...")
    repos = read_text_file(os.path.join(dir_path, "setup.py"))
    repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
    repos = re.sub('git\+https://github.com/agoravoting/agora-tally\.git@.*', 'git+https://github.com/agoravoting/agora-tally.git@'+ version, repos)
    write_text_file(os.path.join(dir_path, "setup.py"), repos)

def do_agora_payment_api(dir_path, version):
    print("setup.py...")
    repos = read_text_file(os.path.join(dir_path, "setup.py"))
    repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
    write_text_file(os.path.join(dir_path, "setup.py"), repos)

def do_authapi(dir_path, version):
    pass

def do_agora_tools(dir_path, version):
    print("setup.py...")
    repos = read_text_file(os.path.join(dir_path, "setup.py"))
    repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
    write_text_file(os.path.join(dir_path, "setup.py"), repos)

def do_vfork(dir_path, version):
    print("project.spdx.yml..")
    spdx = read_text_file(os.path.join(dir_path, "project.spdx.yml"))
    spdx = re.sub(
        "^name:\s*\"vfork-[^\"]+\"\s*", 
        "name: \"vfork-" + version +"\"\n", 
        spdx
    )
    spdx = re.sub(
        "  name:\s*\"vfork\"\s*\n  versionInfo:\s*\"[^\"]+\"", 
        f"  name: \"vfork\"\n  versionInfo: \"{version}\"", 
        spdx,
        flags=re.MULTILINE
    )
    spdx = re.sub(
        'downloadLocation: "git\+https://github.com/agoravoting/vfork\.git@.*\"',
        f'downloadLocation: "git+https://github.com/agoravoting/vfork.git@{version}\"',
        spdx
    )
    write_text_file(os.path.join(dir_path, "project.spdx.yml"), spdx)

def do_admin_manual(dir_path, version):
    print("package.json...")
    package = read_text_file(os.path.join(dir_path, "package.json"))
    package = re.sub('"version"\s*:\s*"[^"]+"', '"version" : "'+ version + '"', package)
    write_text_file(os.path.join(dir_path, "package.json"), package)


def do_agora_release(dir_path, version):
    pass

def apply_base_branch(dir_path, base_branch):
    print("applying base_branch..")
    call_process(f"git stash", shell=True, cwd=dir_path)
    call_process(f"git fetch origin {base_branch}", shell=True, cwd=dir_path)
    call_process(f"git clean -f -d", shell=True, cwd=dir_path)
    call_process(f"git checkout {base_branch}", shell=True, cwd=dir_path)
    call_process(f"git reset --hard origin/{base_branch}", shell=True, cwd=dir_path)

def do_create_branch(dir_path, create_branch, version):
    print("creating branch..")
    call_process(f"git branch -D {create_branch}", shell=True, cwd=dir_path)
    call_process(f"git checkout -b {create_branch}", shell=True, cwd=dir_path)
    call_process(f"git add -u && git add *", shell=True, cwd=dir_path)
    call_process(
        f"git status && git commit -m \"Release for version {version}\"",
        shell=True,
        cwd=dir_path
    )
    call_process(f"git push origin {create_branch} --force", shell=True, cwd=dir_path)

def do_create_tag(dir_path, version):
    print("creating tag..")
    call_process(
        f"git tag {version} --force -a -m \"Release tag for version {version}\"",
        shell=True, 
        cwd=dir_path
    )
    call_process(f"git push origin {version} --force", shell=True, cwd=dir_path)

def call_process(command, *args, **kwargs):
    print(f"Executing: {command}")
    subprocess.call(command, *args, **kwargs)

def do_create_release(
    dir_path,
    version, 
    release_draft,
    release_title,
    release_notes_file, 
    prerelease
):
    print("creating release..")
    release_notes_opt = f"--notes-file {release_notes_file}" if release_notes_file is not None else ""
    release_draft_opt = "--draft" if release_draft else ""
    release_title_opt = f"--title \"{release_title}\"" if release_title is not None else ""
    prerelease_opt = "--prerelease" if prerelease else ""
    
    call_process(f"git fetch --tags origin", shell=True, cwd=dir_path)
    call_process(
        f"gh release create {version} {release_notes_opt} {release_draft_opt} {release_title_opt} {prerelease_opt}",
        shell=True, 
        cwd=dir_path
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--change-version",
        action="store_true",
        help="Execute the version changing scripts specific for the project"
    )
    parser.add_argument(
        "--version", 
        type=str, 
        help="version name",
        metavar="1.3.2"
    )
    parser.add_argument(
        "--path",
        type=str,
        help="project directory path",
        metavar="../agora-gui-booth"
    )
    parser.add_argument(
        "--parent-path",
        type=str,
        help="directory parent to all the projects",
        metavar="path/to/dir"
    )
    parser.add_argument(
        "--base-branch",
        type=str,
        help="use a specific base branch instead of the current one",
        metavar="v2.x"
    )
    parser.add_argument(
        "--create-branch",
        type=str,
        help="create the branch for this release",
        metavar="v1.x"
    )
    parser.add_argument(
        "--create-tag",
        action="store_true",
        help="create the tag for this release"
    )
    parser.add_argument(
        "--create-release",
        action="store_true",
        help="create the github release, requires gh command"
    )
    parser.add_argument(
        "--release-draft",
        action="store_true",
        help="github draft release"
    )
    parser.add_argument(
        "--release-title",
        type=str,
        help="github release title",
        metavar="\"v1.3.2 (beta 1)\""
    )
    parser.add_argument(
        "--release-notes-file",
        type=str,
        help="github release notes file",
        metavar="path/to/notes-file"
    )
    parser.add_argument(
        "--prerelease",
        action="store_true",
        help="github release notes"
    )
    args = parser.parse_args()
    change_version = args.change_version
    version = args.version
    base_branch = args.base_branch
    create_branch = args.create_branch
    create_tag = args.create_tag
    create_release = args.create_release
    release_draft = args.release_draft
    release_title = args.release_title
    prerelease = args.prerelease
    
    path = args.path
    parent_path = args.parent_path
    if path is not None:
        if not os.path.isdir(path):
            raise Exception(path + ": path does not exist or is not a directory")
        path = os.path.realpath(path)
        parent_path = os.path.dirname(path)
    elif parent_path is not None:
        if not os.path.isdir(parent_path):
            raise Exception(parent_path + ": path does not exist or is not a directory")
        parent_path = os.path.realpath(parent_path)
    
    release_notes_file = args.release_notes_file
    if release_notes_file is not None:
        if not os.path.isfile(release_notes_file):
            raise Exception(release_notes_file + ": path does not exist or is not a file")
        release_notes_file = os.path.realpath(release_notes_file)

    print(f"""Options:
 - change-version: {change_version}
 - version: {version}
 - path: {path}
 - parent_path: {parent_path}
 - base_branch: {base_branch}
 - create_branch: {create_branch}
 - create_tag: {create_tag}
 - create_release: {create_release}
 - release_draft: {release_draft}
 - release_title: {release_title}
 - release_notes_file: {release_notes_file}
 - prerelease: {prerelease}
 """)

    if path is not None:
        projects = [ get_project_type(path) ]
    else:
        projects = [
            "agora-gui-common",
            "agora-gui-admin",
            "agora-gui-elections",
            "agora-gui-booth",
            "agora-verifier",
            "agora_elections",
            "agora-dev-box",
            "agora-results",
            "agora-tally",
            "frestq",
            "election-orchestra",
            "authapi",
            "agora-tools",
            "vfork",
            "admin-manual",
            "agora-release"
        ]

    for project_type in projects:
        if path is not None:
            project_path = path
        else:
            project_path = os.path.join(parent_path, project_type)

        print("project: " + project_type)

        if base_branch is not None:
           apply_base_branch(project_path, base_branch)
        
        if change_version:
            if 'agora-gui-common' == project_type:
                do_gui_common(project_path, version)
            elif 'agora-gui-admin' == project_type:
                do_gui_other(project_path, version)
            elif 'agora-gui-elections' == project_type:
                do_gui_other(project_path, version)
            elif 'agora-gui-booth' == project_type:
                do_gui_other(project_path, version)
            elif 'election-orchestra' == project_type:
                do_election_orchestra(project_path, version)
            elif 'agora-verifier' == project_type:
                do_agora_verifier(project_path, version)
            elif 'agora_elections' == project_type:
                do_agora_elections(project_path, version)
            elif 'agora-dev-box' == project_type:
                do_agora_dev_box(project_path, version)
            elif 'agora-results' == project_type:
                do_agora_results(project_path, version)
            elif 'agora-tally' == project_type:
                do_agora_results(project_path, version)
            elif 'frestq' == project_type:
                do_agora_results(project_path, version)
            elif 'authapi' == project_type:
                do_authapi(project_path, version)
            elif 'agora-tools' == project_type:
                do_agora_tools(project_path, version)
            elif 'vfork' == project_type:
                do_vfork(project_path, version)
            elif 'admin-manual' == project_type:
                do_admin_manual(project_path, version)
            elif 'agora-release' == project_type:
                do_agora_release(project_path, version)
        
        if create_branch is not None:
            do_create_branch(project_path, create_branch, version)
        if create_tag:
            do_create_tag(project_path, version)
        if create_release:
            do_create_release(
                project_path,
                version,
                release_draft,
                release_title,
                release_notes_file, 
                prerelease
            )

    print("done")

if __name__ == "__main__":
    main()
