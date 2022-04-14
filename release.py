#!/usr/bin/env python3

# This file is part of release-tool.
# Copyright (C) 2016-2021 Sequent Tech Inc <legal@sequentech.io>

# release-tool is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License.

# release-tool  is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with release-tool.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import requests
import tempfile
from datetime import datetime
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
    my_match = re.search('url\s*=\s*git@(github|gitlab).com:(sequentech)/(?P<proj_name>.+)(\.git|)', config_file)

    try:
        my_match.group('proj_name')
    except:
        my_match = re.search('url\s*=\s*https://(github|gitlab).com/(sequentech)/(?P<proj_name>.+)(\.git|)', config_file)

    return my_match.group('proj_name')

def do_gui_common(dir_path, version):
    invalid_version = re.match(r"^[a-zA-Z]+", version) is not None

    print("SequentConfig.js...")
    SequentConfig = read_text_file(os.path.join(dir_path, "SequentConfig.js"))
    SequentConfig = re.sub(
        "var\s+SEQUENT_CONFIG_VERSION\s*=\s*'[^']+';",
        "var SEQUENT_CONFIG_VERSION = '" + version + "';",
        SequentConfig
    )
    SequentConfig = re.sub(
        "mainVersion\s*[^,]+,\n",
        "mainVersion: '" + version + "',\n",
        SequentConfig
    )
    write_text_file(os.path.join(dir_path, "SequentConfig.js"), SequentConfig)

    print("package.json...")
    if not invalid_version:
        package = read_text_file(os.path.join(dir_path, "package.json"))
        package = re.sub('"version"\s*:\s*"[^"]+"', '"version" : "'+ version + '"', package)
        write_text_file(os.path.join(dir_path, "package.json"), package)
    else:
        print("leaving package.json as is because of invalid version name")

    print("Gruntfile.js...")
    Gruntfile = read_text_file(os.path.join(dir_path, "Gruntfile.js"))
    Gruntfile = re.sub("var\s+SEQUENT_CONFIG_VERSION\s*=\s*'[^']+';", "var SEQUENT_CONFIG_VERSION = '" + version + "';", Gruntfile)
    Gruntfile = re.sub("appCommon-v[0-9a-zA-Z.\-+]+\.js", "appCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libCommon-v[0-9a-zA-Z.\-+]+\.js", "libCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libnocompat-v[0-9a-zA-Z.\-+]+\.js", "libnocompat-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libcompat-v[0-9a-zA-Z.\-+]+\.js", "libcompat-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("SequentConfig-v[0-9a-zA-Z.\-+]+\.js", "SequentConfig-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("SequentThemes-v[0-9a-zA-Z.\-+]+\.js", "SequentThemes-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("SequentPlugins-v[0-9a-zA-Z.\-+]+\.js", "SequentPlugins-v" + version + ".js", Gruntfile)
    write_text_file(os.path.join(dir_path, "Gruntfile.js"), Gruntfile)

    print("running grunt build..")
    call_process("grunt build", shell=True, cwd=dir_path)

def do_gui_other(dir_path, version):
    print("index.html...")
    index = read_text_file(os.path.join(dir_path, "index.html"))
    index = re.sub("libnocompat-v.*\.js", "libnocompat-v" + version + ".js", index)
    index = re.sub("libcompat-v.*\.js", "libcompat-v" + version + ".js", index)
    index = re.sub("SequentTheme-v.*\.js", "SequentTheme-v" + version + ".js", index)
    index = re.sub("appCommon-v.*\.js", "appCommon-v" + version + ".js", index)
    index = re.sub("libCommon-v.*\.js", "libCommon-v" + version + ".js", index)
    write_text_file(os.path.join(dir_path, "index.html"), index)

    print("SequentConfig.js...")
    SequentConfig = read_text_file(os.path.join(dir_path, "SequentConfig.js"))
    SequentConfig = re.sub(
        "var\s+SEQUENT_CONFIG_VERSION\s*=\s*'[^']+';",
        "var SEQUENT_CONFIG_VERSION = '" + version + "';",
        SequentConfig
    )
    SequentConfig = re.sub(
        "mainVersion\s*[^,]+,\n",
        "mainVersion: '" + version + "',\n",
        SequentConfig
    )
    write_text_file(os.path.join(dir_path, "SequentConfig.js"), SequentConfig)

    av_plugins_config_path = os.path.join(dir_path, "SequentPluginsConfig.js")
    if os.path.isfile(av_plugins_config_path):
        print("SequentPluginsConfig.js...")
        SequentPluginsConfig = read_text_file(av_plugins_config_path)
        SequentPluginsConfig = re.sub("var\s+SEQUENT_PLUGINS_CONFIG_VERSION\s*=\s*'[^']+';", "var SEQUENT_PLUGINS_CONFIG_VERSION = '" + version + "';", SequentPluginsConfig)
        write_text_file(av_plugins_config_path, SequentPluginsConfig)

    print("Gruntfile.js...")
    Gruntfile = read_text_file(os.path.join(dir_path, "Gruntfile.js"))
    Gruntfile = re.sub("var\s+SEQUENT_CONFIG_VERSION\s*=\s*'[^']+';", "var SEQUENT_CONFIG_VERSION = '" + version + "';", Gruntfile)
    Gruntfile = re.sub("appCommon-v[0-9a-zA-Z.\-+]+\.js", "appCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libCommon-v[0-9a-zA-Z.\-+]+\.js", "libCommon-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("libnocompat-v[0-9a-zA-Z.\-+]+\.min\.js", "libnocompat-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("libcompat-v[0-9a-zA-Z.\-+]+\.min\.js", "libcompat-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("SequentConfig-v[0-9a-zA-Z.\-+]+\.js", "SequentConfig-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("SequentThemes-v[0-9a-zA-Z.\-+]+\.js", "SequentThemes-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("SequentPlugins-v[0-9a-zA-Z.\-+]+\.js", "SequentPlugins-v" + version + ".js", Gruntfile)
    Gruntfile = re.sub("app-v[0-9a-zA-Z.\-+]+\.min\.js", "app-v" + version + ".min.js", Gruntfile)
    Gruntfile = re.sub("lib-v[0-9a-zA-Z.\-+]+\.min\.js", "lib-v" + version + ".min.js", Gruntfile)
    write_text_file(os.path.join(dir_path, "Gruntfile.js"), Gruntfile)

    print("package.json...")
    package = read_text_file(os.path.join(dir_path, "package.json"))
    package = re.sub('"version"\s*:\s*"[^"]+"', '"version" : "'+ version + '"', package)
    package = re.sub(
        '"common-ui": "https://github.com/sequentech/common-ui\.git.*\"',
        f'"common-ui": "https://github.com/sequentech/common-ui.git#{version}\"',
        package
    )
    write_text_file(os.path.join(dir_path, "package.json"), package)

def do_ballot_box(dir_path, version):
    print("build.sbt...")
    build = read_text_file(os.path.join(dir_path, "build.sbt"))
    build = re.sub('version\s*:=\s*"[^"]+"', 'version := "'+ version + '"', build)
    write_text_file(os.path.join(dir_path, "build.sbt"), build)

def do_election_verifier(dir_path, version):
    print("build.sbt...")
    build = read_text_file(os.path.join(dir_path, "build.sbt"))
    build = re.sub('version\s*:=\s*"[^"]+"', 'version := "'+ version + '"', build)
    m = re.search('scalaVersion := "(?P<scalaVersion>[0-9]+\.[0-9]+)\.[0-9]"', build)
    scalaVersion = m.group('scalaVersion')
    print("scalaVersion is " + scalaVersion)
    write_text_file(os.path.join(dir_path, "build.sbt"), build)

    print("package.sh...")
    package = read_text_file(os.path.join(dir_path, "package.sh"))
    package = re.sub(
        'cp target/scala-.*/proguard/election-verifier_.*\.jar dist',
        'cp target/scala-' + scalaVersion + '/proguard/election-verifier_' + scalaVersion +  '-' + version + '.jar dist',
        package
    )
    write_text_file(os.path.join(dir_path, "package.sh"), package)

    print('pverify.sh..')
    pverify = read_text_file(os.path.join(dir_path, "pverify.sh"))
    pverify = re.sub(
        'java -Djava\.security\.egd=file:/dev/\./urandom -classpath election-verifier_.*\.jar org\.sequent\.sequent\.Verifier \$1 \$2',
        'java -Djava.security.egd=file:/dev/./urandom -classpath election-verifier_' + scalaVersion + '-'  + version + '.jar org.sequent.sequent.Verifier $1 $2',
        pverify
    )
    write_text_file(os.path.join(dir_path, "pverify.sh"), pverify)

    print('vmnc.sh..')
    vmnc = read_text_file(os.path.join(dir_path, "vmnc.sh"))
    vmnc = re.sub(
        'java -Djava.security\.egd=file:/dev/\./urandom -classpath \$DIR/election-verifier_.*\.jar org\.sequent\.sequent\.Vmnc "\$@"',
        'java -Djava.security.egd=file:/dev/./urandom -classpath $DIR/election-verifier_' + scalaVersion + '-' + version + '.jar org.sequent.sequent.Vmnc "$@"',
        vmnc
    )
    write_text_file(os.path.join(dir_path, "vmnc.sh"), vmnc)

    print('README.md..')
    readme = read_text_file(os.path.join(dir_path, "README.md"))
    readme = re.sub(
        'using version `[^`]+`',
        'using version `' + version + '`',
        readme
    )
    readme = re.sub(
        'export INTERNAL_GIT_VERSION=.*',
        'export INTERNAL_GIT_VERSION="' + version + '"',
        readme
    )
    write_text_file(os.path.join(dir_path, "README.md"), readme)

    print("project.spdx.yml..")
    spdx = read_text_file(os.path.join(dir_path, "project.spdx.yml"))
    spdx = re.sub(
        "name:\s*\"election-verifier-[^\"]+\"\s*", 
        "name: \"election-verifier-" + version +"\"\n", 
        spdx
    )
    spdx = re.sub(
        "  name:\s*\"election-verifier\"\s*\n  versionInfo:\s*\"[^\"]+\"", 
        f"  name: \"election-verifier\"\n  versionInfo: \"{version}\"", 
        spdx,
        flags=re.MULTILINE
    )
    spdx = re.sub(
        'downloadLocation: "git\+https://github.com/sequentech/election-verifier\.git@.*\"',
        f'downloadLocation: "git+https://github.com/sequentech/election-verifier.git@{version}\"',
        spdx
    )
    write_text_file(os.path.join(dir_path, "project.spdx.yml"), spdx)

    print(".github/workflows/unittests.yml...")
    unittests_yml_path = os.path.join(
        dir_path, ".github", "workflows", "unittests.yml"
    )
    unittests_yml = read_text_file(unittests_yml_path)
    unittests_yml = re.sub(
        'export INTERNAL_GIT_VERSION=.*',
        f'export INTERNAL_GIT_VERSION="{version}"',
        unittests_yml
    )
    write_text_file(unittests_yml_path, unittests_yml)

    print("config.json in unit tests tarfdiles")
    testdata_path = os.path.join(dir_path, "testdata")
    tar_files = [
        filename
        for filename in os.listdir(testdata_path)
        if (
            os.path.isfile(os.path.join(testdata_path, filename)) and
            filename.endswith(".tar")
        )
    ]
    # untar the tarfiles, edit them and recreate them
    for tarfile_name in tar_files:
        tarfile_path = os.path.join(testdata_path, tarfile_name)
        with tempfile.TemporaryDirectory() as temp_dir:
            call_process(
                f"tar xf {tarfile_path} -C {temp_dir}",
                shell=True,
                cwd=dir_path
            )
            config_json_path = os.path.join(temp_dir, "config.json")
            config_json = read_text_file(config_json_path)
            config_json = re.sub(
                "{\"version\"\s*:\s*\"[^\"]+\"\s*,", 
                "{\"version\": \"" + version +"\",",
                config_json
            )
            write_text_file(config_json_path, config_json)
            call_process(
                f"tar cf {tarfile_path} -C {temp_dir} .",
                shell=True,
                cwd=dir_path
            )

def do_frestq(dir_path, version):
    invalid_version = re.match(r"^[a-zA-Z]+", version) is not None

    print("setup.py...")
    if not invalid_version:
        repos = read_text_file(os.path.join(dir_path, "setup.py"))
        repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
        write_text_file(os.path.join(dir_path, "setup.py"), repos)
    else:
        print("leaving setup.py as is because of invalid version name")

def do_election_orchestra(dir_path, version):
    print("requirements.txt...")
    requirements = read_text_file(os.path.join(dir_path, "requirements.txt"))
    requirements = re.sub(
        'git\+https://github.com/sequentech/frestq\.git@.*', 
        'git+https://github.com/sequentech/frestq.git@'+ version, 
        requirements
    )
    write_text_file(os.path.join(dir_path, "requirements.txt"), requirements)

    setup_py = read_text_file(os.path.join(dir_path, "setup.py"))
    setup_py = re.sub(
        "version\s*=\s*'[^']+'\s*,",
        "version='" + version +"',",
        setup_py
    )
    setup_py = re.sub(
        'git\+https://github.com/sequentech/frestq\.git@[^\'"]+', 
        'git+https://github.com/sequentech/frestq.git@'+ version,
        setup_py
    )
    write_text_file(os.path.join(dir_path, "setup.py"), setup_py)

def do_deployment_tool(dir_path, version):
    print("repos.yml...")
    repos = read_text_file(os.path.join(dir_path, "repos.yml"))
    repos = re.sub('version:\s*.*\n', 'version: \''+ version + '\'\n', repos)
    write_text_file(os.path.join(dir_path, "repos.yml"), repos)

    print("config.yml...")
    repos = read_text_file(os.path.join(dir_path, "config.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub(
        '"version":\s*"[^"]+",\n',
        '"version": "'+ version + '",\n',
        repos
    )
    repos = re.sub(
        'mainVersion:\s*[^,]+,\n',
        'mainVersion: \''+ version + '\',\n',
        repos
    )
    write_text_file(os.path.join(dir_path, "config.yml"), repos)

    print("doc/devel/sequent.config.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/devel/sequent.config.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub('"version":\s*"[^"]+",\n', '"version": "'+ version + '",\n', repos)
    write_text_file(os.path.join(dir_path, "doc/devel/sequent.config.yml"), repos)

    print("doc/devel/auth1.config.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/devel/auth1.config.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub('"version":\s*"[^"]+",\n', '"version": "'+ version + '",\n', repos)
    write_text_file(os.path.join(dir_path, "doc/devel/auth1.config.yml"), repos)

    print("doc/devel/auth2.config.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/devel/auth2.config.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub('"version":\s*"[^"]+",\n', '"version": "'+ version + '",\n', repos)
    write_text_file(os.path.join(dir_path, "doc/devel/auth2.config.yml"), repos)

    print("doc/production/config.auth.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/production/config.auth.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub('"version":\s*"[^"]+",\n', '"version": "'+ version + '",\n', repos)
    write_text_file(os.path.join(dir_path, "doc/production/config.auth.yml"), repos)

    print("doc/production/config.master.yml...")
    repos = read_text_file(os.path.join(dir_path, "doc/production/config.master.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub('"version":\s*"[^"]+",\n', '"version": "'+ version + '",\n', repos)
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

    print("sequent-ui/templates/SequentConfig.js...")
    Gruntfile = read_text_file(os.path.join(dir_path, "sequent-ui/templates/SequentConfig.js"))
    Gruntfile = re.sub("var\s+SEQUENT_CONFIG_VERSION\s*=\s*'[^']+';", "var SEQUENT_CONFIG_VERSION = '" + version + "';", Gruntfile)
    write_text_file(os.path.join(dir_path, "sequent-ui/templates/SequentConfig.js"), Gruntfile)

def do_tally_methods(dir_path, version):
    invalid_version = re.match(r"^[a-zA-Z]+", version) is not None

    print("setup.py...")
    if not invalid_version:
        repos = read_text_file(os.path.join(dir_path, "setup.py"))
        repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
        write_text_file(os.path.join(dir_path, "setup.py"), repos)
    else:
        print("leaving setup.py as is because of invalid version name")

def do_tally_pipes(dir_path, version):
    print("setup.py...")
    repos = read_text_file(os.path.join(dir_path, "setup.py"))
    repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
    repos = re.sub('git\+https://github.com/sequentech/tally-methods\.git@.*', 'git+https://github.com/sequentech/tally-methods.git@'+ version + '\'', repos)
    write_text_file(os.path.join(dir_path, "setup.py"), repos)

    print("requirements.txt...")
    requirements = read_text_file(os.path.join(dir_path, "requirements.txt"))
    requirements = re.sub('git\+https://github.com/sequentech/tally-methods\.git@.*', 'git+https://github.com/sequentech/tally-methods.git@'+ version + "#egg=tally-methods", requirements)
    write_text_file(os.path.join(dir_path, "requirements.txt"), requirements)

    print("tally_pipes/main.py...")
    main_path = os.path.join(dir_path, "tally_pipes/main.py")
    if os.path.isfile(main_path):
        main_file = read_text_file(main_path)
        main_file = re.sub("VERSION\s*=\s*\"[^\"]+\"", "VERSION = \"" + version + "\"", main_file)
        write_text_file(main_path, main_file)

def do_sequent_payment_api(dir_path, version):
    print("setup.py...")
    repos = read_text_file(os.path.join(dir_path, "setup.py"))
    repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
    write_text_file(os.path.join(dir_path, "setup.py"), repos)

def do_iam(dir_path, version):
    pass

def do_misc_tools(dir_path, version):
    print("setup.py...")
    repos = read_text_file(os.path.join(dir_path, "setup.py"))
    repos = re.sub("version\s*=\s*'[^']+'\s*,", "version='" + version +"',", repos)
    write_text_file(os.path.join(dir_path, "setup.py"), repos)

def do_mixnet(dir_path, version):
    print("project.spdx.yml..")
    spdx = read_text_file(os.path.join(dir_path, "project.spdx.yml"))
    str_datetime = datetime.now().isoformat(timespec="seconds")
    spdx = re.sub(
        "created:\s*\"[^\"]+\"\s*\n", 
        "created: \"" + str_datetime + "Z\"\n", 
        spdx
    )
    spdx = re.sub(
        "^name:\s*\"mixnet-[^\"]+\"\s*", 
        "name: \"mixnet-" + version + "\"\n", 
        spdx
    )
    spdx = re.sub(
        "  name:\s*\"mixnet\"\s*\n  versionInfo:\s*\"[^\"]+\"", 
        f"  name: \"mixnet\"\n  versionInfo: \"{version}\"", 
        spdx,
        flags=re.MULTILINE
    )
    spdx = re.sub(
        'downloadLocation: "git\+https://github.com/sequentech/mixnet\.git@.*\"',
        f'downloadLocation: "git+https://github.com/sequentech/mixnet.git@{version}\"',
        spdx
    )
    write_text_file(os.path.join(dir_path, "project.spdx.yml"), spdx)

def do_ballot_verifier(dir_path, version):
    print("README.md...")
    print("project.spdx.yml..")
    spdx = read_text_file(os.path.join(dir_path, "project.spdx.yml"))
    str_datetime = datetime.now().isoformat(timespec="seconds")
    spdx = re.sub(
        "created:\s*\"[^\"]+\"\s*\n", 
        "created: \"" + str_datetime + "Z\"\n", 
        spdx
    )
    spdx = re.sub(
        "^name:\s*\"ballot-verifier-[^\"]+\"\s*", 
        "name: \"ballot-verifier-" + version + "\"\n", 
        spdx
    )
    spdx = re.sub(
        "  name:\s*\"ballot-verifier\"\s*\n  versionInfo:\s*\"[^\"]+\"", 
        f"  name: \"ballot-verifier\"\n  versionInfo: \"{version}\"", 
        spdx,
        flags=re.MULTILINE
    )
    spdx = re.sub(
        'downloadLocation: "git\+https://github.com/sequentech/ballot-verifier\.git@.*\"',
        f'downloadLocation: "git+https://github.com/sequentech/ballot-verifier.git@{version}\"',
        spdx
    )
    write_text_file(os.path.join(dir_path, "project.spdx.yml"), spdx)

    readme = read_text_file(os.path.join(dir_path, "README.md"))
    readme = re.sub(
        'https://github\.com/sequentech/ballot-verifier/releases/download/[^/]+/',
        f'https://github.com/sequentech/ballot-verifier/releases/download/{version}/',
        readme)
    write_text_file(os.path.join(dir_path, "README.md"), readme)

def do_documentation(dir_path, version):
    print("package.json...")
    package = read_text_file(os.path.join(dir_path, "package.json"))
    package = re.sub('"version"\s*:\s*"[^"]+"', '"version" : "'+ version + '"', package)
    write_text_file(os.path.join(dir_path, "package.json"), package)

    print("docs/deployment/assets/config.auth.yml...")
    repos = read_text_file(os.path.join(dir_path, "docs/deployment/assets/config.auth.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub(
        'mainVersion:\s*\'[^\']+\'\n',
        f'mainVersion: \'{version}\'\n',
        repos
    )
    repos = re.sub('"version":\s*"[^"]+",\n', '"version": "'+ version + '",\n', repos)
    write_text_file(os.path.join(dir_path, "docs/deployment/assets/config.auth.yml"), repos)

    print("docs/deployment/assets/config.master.yml...")
    repos = read_text_file(os.path.join(dir_path, "docs/deployment/assets/config.master.yml"))
    repos = re.sub('version:\s*.*[^,]\n', 'version: \''+ version + '\'\n', repos)
    repos = re.sub(
        "tallyPipesConfig: {\n(\s*)version:\s*\'[^\']+\',?\n",
        f"tallyPipesConfig: {{\n\\1version: \'{version}\',\n",
        repos
    )
    repos = re.sub(
        'mainVersion:\s*\'[^\']+\'\n',
        f'mainVersion: \'{version}\'\n',
        repos
    )
    repos = re.sub('"version":\s*"[^"]+",\n', '"version": "'+ version + '",\n', repos)
    write_text_file(os.path.join(dir_path, "docs/deployment/assets/config.master.yml"), repos)

def do_release_tool(dir_path, version):
    pass

def apply_base_branch(dir_path, base_branch):
    print("applying base_branch..")
    call_process(f"git stash", shell=True, cwd=dir_path)
    call_process(f"git fetch origin {base_branch}", shell=True, cwd=dir_path)
    call_process(f"git clean -f -d", shell=True, cwd=dir_path)
    call_process(f"git checkout {base_branch}", shell=True, cwd=dir_path)
    call_process(f"git reset --hard origin/{base_branch}", shell=True, cwd=dir_path)

def do_commit_push_branch(dir_path, base_branch, version):
    print(f"commit and push to base branch='{base_branch}'..")
    call_process(f"git add -u && git add *", shell=True, cwd=dir_path)
    call_process(
        f"git status && git commit -m \"Release for version {version}\"",
        shell=True,
        cwd=dir_path
    )
    call_process(
        f"git push origin {base_branch} --force",
        shell=True,
        cwd=dir_path
    )

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
    return subprocess.call(command, *args, **kwargs)

def do_create_release(
    dir_path,
    version, 
    release_draft,
    release_title,
    release_notes_file,
    generate_release_notes,
    previous_tag_name,
    prerelease
):
    with tempfile.NamedTemporaryFile() as temp_release_file:
        generated_release_title = ''
        if generate_release_notes:
            dir_name = os.path.basename(dir_path)
            data = {
                'tag_name': version,
            }
            if previous_tag_name is not None:
                data['previous_tag_name'] = previous_tag_name
            req = requests.post(
                f'https://api.github.com/repos/sequentech/{dir_name}/releases/generate-notes',
                headers={
                    "Accept": "application/vnd.github.v3+json"
                },
                json=data,
                auth=(
                    os.getenv('GITHUB_USER'),
                    os.getenv('GITHUB_TOKEN'),
                )
            )
            if req.status_code != 200:
                print(f"Error generating release notes, status ${req.status_code}")
                exit(1)
            
            generated_release_notes = req.json()['body']
            temp_release_file.write(generated_release_notes.encode('utf-8'))
            temp_release_file.flush()
            generated_release_title = req.json()['name']
            print(f"- github-generated release notes:\n\n{generated_release_notes}\n\n")

        print("checking if release exists to overwrite it..")
        ret_code = call_process(
            f"gh release view {version}",
            shell=True,
            cwd=dir_path
        )
        if ret_code == 0:
            # release exists, so remove it first
            ret_code = call_process(
                f"gh release delete {version}",
                shell=True,
                cwd=dir_path
            )
            if ret_code != 0:
                print("Error: couldn't remove existing release")
                exit(1)

        print("creating release..")
        release_file_path = (
            release_notes_file
            if release_notes_file is not None 
            else temp_release_file.name
        )
        release_notes_opt = f"--notes-file \"{release_file_path}\"\\\n"
        release_title_opt = (
            f"--title \"{release_title}\"\\\n" 
            if release_title is not None
            else generated_release_title
        )
        release_draft_opt = "--draft\\\n" if release_draft else ""
        prerelease_opt = "--prerelease\\\n" if prerelease else ""

        call_process(f"git fetch --tags origin", shell=True, cwd=dir_path)
        release_opts_str = " ".join([
            version, 
            release_title_opt,
            release_notes_opt,
            release_draft_opt,
            prerelease_opt
        ])
        ret_code = call_process(
            f"gh release create {release_opts_str}",
            shell=True, 
            cwd=dir_path
        )
        if ret_code != 0:
            print("Error: couldn't create the release")
            exit(1)



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
        metavar="../voting-booth"
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
        "--push-current-branch",
        action="store_true",
        help="push and commit changes to the current branch"
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
        "--previous-tag-name",
        type=str,
        help="previous release tag name",
        metavar="\"5.3.4\""
    )
    parser.add_argument(
        "--release-notes-file",
        type=str,
        help="github release notes file",
        metavar="path/to/notes-file"
    )
    parser.add_argument(
        "--generate-release-notes",
        action="store_true",
        help="use github automatic release generation"
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
    push_current_branch = args.push_current_branch
    create_tag = args.create_tag
    create_release = args.create_release
    release_draft = args.release_draft
    release_title = args.release_title
    prerelease = args.prerelease
    generate_release_notes = args.generate_release_notes
    previous_tag_name = args.previous_tag_name
    
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
 - push_current_branch: {push_current_branch}
 - create_tag: {create_tag}
 - create_release: {create_release}
 - release_draft: {release_draft}
 - release_title: {release_title}
 - release_notes_file: {release_notes_file}
 - generate_release_notes: {generate_release_notes}
 - previous_tag_name: {previous_tag_name}
 - prerelease: {prerelease}
 """)

    if path is not None:
        projects = [ get_project_type(path) ]
    else:
        projects = [
            "common-ui",
            "admin-console",
            "election-portal",
            "voting-booth",
            "election-verifier",
            "ballot_box",
            "deployment-tool",
            "tally-pipes",
            "tally-methods",
            "frestq",
            "election-orchestra",
            "iam",
            "misc-tools",
            "mixnet",
            "documentation",
            "release-tool"
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
            if 'common-ui' == project_type:
                do_gui_common(project_path, version)
            elif 'admin-console' == project_type:
                do_gui_other(project_path, version)
            elif 'election-portal' == project_type:
                do_gui_other(project_path, version)
            elif 'voting-booth' == project_type:
                do_gui_other(project_path, version)
            elif 'election-orchestra' == project_type:
                do_election_orchestra(project_path, version)
            elif 'election-verifier' == project_type:
                do_election_verifier(project_path, version)
            elif 'ballot_box' == project_type:
                do_ballot_box(project_path, version)
            elif 'deployment-tool' == project_type:
                do_deployment_tool(project_path, version)
            elif 'tally-pipes' == project_type:
                do_tally_pipes(project_path, version)
            elif 'tally-methods' == project_type:
                do_tally_methods(project_path, version)
            elif 'frestq' == project_type:
                do_frestq(project_path, version)
            elif 'iam' == project_type:
                do_iam(project_path, version)
            elif 'misc-tools' == project_type:
                do_misc_tools(project_path, version)
            elif 'mixnet' == project_type:
                do_mixnet(project_path, version)
            elif 'documentation' == project_type:
                do_documentation(project_path, version)
            elif 'ballot-verifier' == project_type:
                do_ballot_verifier(project_path, version)
            elif 'release-tool' == project_type:
                do_release_tool(project_path, version)
        
        if create_branch is not None:
            do_create_branch(project_path, create_branch, version)
        elif push_current_branch:
            do_commit_push_branch(project_path, base_branch, version)
        if create_tag:
            do_create_tag(project_path, version)
        if create_release:
            do_create_release(
                project_path,
                version,
                release_draft,
                release_title,
                release_notes_file,
                generate_release_notes,
                previous_tag_name,
                prerelease
            )

    print("done")

if __name__ == "__main__":
    main()
