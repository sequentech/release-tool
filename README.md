# release-tool

scripts used for creating a new release

This repo contains the release.py script, which is used to update the version
number for all other Sequent Tech projects. In order to use the script, please
read the documentation in [https://sequent.github.io/documentation/docs/contribute/release-howto].

# Setup

First, download `release-tool` repository and install the dependencies. It
uses Python 3 so you need it installed:

```bash
git clone https://github.com/sequentech/release-tool.git
pip install -r requirements.txt
```

Some other setup steps:
- To execute the `release.py` command, please always do it within the directory 
containing `release-tool`. Meaning, CWD needs to be that directory when 
executing the command.
- You need to have your git's username and email configured, as this command
will create release commits.
- If you are releasing for example the `election-portal` repository, it
needs to be in the parent directory and with the origin remote having write 
permissions and the ssh-agent active to be able to push automatically.
- You need to have the github cli [gh](https://github.com/cli/cli) installed, 
configured and properly authenticated authorized. Follow []
- If you are using the github release notes automatic generation by github with
the `--generate-release-notes` option, then you need to configure the
environment variables `GITHUB_USER` to be your github username and
`GITHUB_TOKEN` to be a [personal access token](https://github.com/settings/tokens).
This token needs to have general repository permissions.
