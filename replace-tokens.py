#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Based on https://github.com/qetza/vsts-replacetokens-task - Copyright (c) 2016 Guillaume Rouchon
import argparse
import fileinput
import sys, os
import re
import codecs
import shutil
import tempfile
import logging
from pathlib import Path
import locale

parser = argparse.ArgumentParser(description='Replace tokens in matched files.')

parser.add_argument('-d','--directory', default='.', help='Base directory for searching files. If not specified the default working directory will be used.')
parser.add_argument('-t','--target', default='./**/*', help='''
    Absolute or relative comma-separated paths to the files to replace tokens (wildcards can be used).
    Example: 'web.config' will replace tokens in web.config and update the file.
    Example: 'config*.tokenized.config => *.config' will replace tokens in config{filename}.tokenized.config and save the result in config{filename}.config.
    ''')
parser.add_argument('-T','--target-exclude', default='', help='Exclude absolute or relative comma-separated paths to the files (wildcards can be used).')
parser.add_argument('-e','--encoding', choices=['ascii', 'utf-7', 'utf-8', 'utf-16', 'utf-16-be', 'windows-1252', 'iso-8859-1'], default='utf-8', help='''
    Specify the files encoding.
    The 'auto' value will determine the encoding based on the Byte Order Mark (BOM) if present; otherwise it will use ascii.
    ''')
parser.add_argument('-b','--backup', action='store_true', help='If checked creates a backup of matching files.')    
parser.add_argument('-m','--bom', action='store_true', help='If checked writes an unicode Byte Order Mark (BOM).')
parser.add_argument('-v','--escape-values', choices=['no-escaping', 'json', 'xml', 'custom'], default='no-escaping', help='Specify how to escape variable values.')
parser.add_argument('-c','--escape-character', default='\\', help='The escape character to use when escaping characters in the variable values.')
parser.add_argument('-x','--characters-escape', default='', help='Characters in variable values to escape before replacing tokens.')
parser.add_argument('-V','--verbosity', choices=['normal', 'detailed', 'off'], default='normal', help='Specify the logs verbosity level. (error and system debug are always on)')
parser.add_argument('-a','--action', choices=['silently-continue', 'log-warning', 'fail'], default='log-warning', help='Specify the action on a missing variable.')
parser.add_argument('-p','--token-prefix', default='#{', help='The prefix of the tokens to search in the target files.')
parser.add_argument('-s','--token-suffix', default='}#', help='The suffix of the tokens to search in the target files.')
parser.add_argument('-k','--keep-token', action='store_true', help='If checked tokens with missing variables will not be replaced by empty string.')
parser.add_argument('-E','--empty-value', default='(empty)', help='The variable value which will be replaced by an empty string.')
parser.add_argument('-j','--tokens-skip', default='', help='Tokens to skip (comma-separated).')
parser.add_argument('-f','--file', default='', help='Path to file that contains tokens (key-value per line).')
parser.add_argument('-F','--force-exist', default='1', help='Force existence of tokens.')

args = parser.parse_args()

if args.verbosity == "normal":
    logging_level = logging.INFO
elif args.verbosity == "detailed":
    logging_level = logging.DEBUG
elif args.verbosity == "off":
    logging_level = logging.CRITICAL

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging_level)

logging.debug('Locale encoding: {0}'.format(locale.getpreferredencoding()))
logging.debug('SYS encoding: {0}'.format(sys.getdefaultencoding()))

if args.file != '':
    if os.path.exists(args.file):
        with open(args.file, 'r', encoding="utf-8") as f:
            for line in f:
                try:
                    index = line.find('=')
                    key = line[:index]
                    value = line[index+1:]
                    os.environ[key] = value
                except Exception as e:
                    logging.error(str(e))
                    logging.error('Error on file parse at line: {0}'.format(line))
                    continue
        logging.debug('File {0} loaded.'.format(args.file))
    else:
        msg_filenotfound = 'File {0} not found.'.format(args.file)
        logging.error(msg_filenotfound)

exit_code = 0
os.chdir(args.directory)
files = []
files_exclude = []
targets = [x.strip() for x in args.target.replace("'","").split(',')]
targets_exclude = [x.strip() for x in args.target_exclude.replace("'","").split(',')]
tokens_skip = [x.strip() for x in args.tokens_skip.split(',')]

# Match files
def matchFiles(directory, target):
    logging.debug("Match {0} in {1}".format(target, directory))
    matches = []
    if target == '':
        return matches
    
    for file_path in Path(directory).glob(target):
        logging.debug("Adding {0} to file_path".format(file_path))
        matches.append(str(file_path))
    return matches

def matchTargets(directory, targets):
    files = []
    for target in targets:
        find_files = matchFiles(directory, target)
        for find_file in find_files:
            if find_file not in files:
                logging.debug("Adding {0} to files.".format(find_file))
                files.append(find_file)
    return files

files = matchTargets(args.directory, targets)
files_exclude = matchTargets(args.directory, targets_exclude)

files = list(set(files) - set(files_exclude))
files = [x for x in files if os.path.isfile(x)]
logging.info("{0} matched files found.".format(len(files)))
tokens_replaced = 0
tokens_skipped = 0

for file_path in files:
    logging.debug("{0} found.".format(file_path))

    if args.backup:
        shutil.copy2(file_path,file_path+".bak")

    file_tmp = tempfile.NamedTemporaryFile().name
    
    # Process file tokens
    with codecs.open(file_path, 'r', encoding=args.encoding) as fi, \
         codecs.open(file_tmp, 'w', encoding=args.encoding) as fo:
        try:
            bom_flag = 0
            for line in fi:
                # Write unicode BOM
                if args.bom and bom_flag == 0:
                    if args.encoding == "utf-7" and not line.startswith('\u2B2F762B'):
                        fo.write(u'\u2B2F762B')
                    elif args.encoding == "utf-8" and not line.startswith('\uEFBBBF'):
                        fo.write(u'\uEFBBBF')
                    elif args.encoding == "utf-16" and not line.startswith('\uFFFE'):
                        fo.write(u'\uFFFE')
                    elif args.encoding == "utf-16-be" and not line.startswith('\uFEFF'):
                        fo.write(u'\uFEFF')
                    bom_flag = 1

                pattern = re.escape(args.token_prefix) + '([A-Za-z0-9_-]*)' + re.escape(args.token_suffix)
                tokens = re.findall(pattern, line)
                for token in tokens:
                    if token in tokens_skip:
                        tokens_skipped = tokens_skipped + 1
                        continue
                    try:
                        value = os.environ.get(token).strip()
                    except:
                        if args.force_exist == '1':
                            exit_code = 1
                            logging.error('Token {0} not found in variable group.'.format(token))
                        else:
                            logging.info('Token {0} not found in variable group.'.format(token))
                            continue
                    
                    if value == '' and args.force_exist == '1':
                        logging.error('Token {0} is blank.'.format(token))
                        exit_code = 1
                    
                    if value != None or not args.keep_token:
                        tokens_replaced = tokens_replaced + 1

                    if value == None:
                        msg_missing = 'Variable {0} not found.'.format(token)
                        if args.action == "fail":
                            exit_code = 1
                            logging.error(msg_missing)
                        elif args.action == "log-warning":
                            logging.warning(msg_missing)
                        value = args.empty_value
                        if args.keep_token:
                            value = args.token_prefix + token + args.token_suffix
                    else:
                        # Characters to escape
                        if args.escape_values == "custom" and args.characters_escape != '':
                            pattern_characters_escape = r"([" + re.escape(args.characters_escape) + r"])"
                            repl = args.escape_character + r"\1"
                            if args.escape_character == "\\":
                                repl = r"\\\1"
                            value = re.sub(pattern_characters_escape, repl, value)

                    line = line.replace(args.token_prefix + token + args.token_suffix, value)
                fo.write(line)
        except Exception as e:
            logging.debug(str(e))
            continue
            
    os.remove(file_path) 
    shutil.copy2(file_tmp, file_path)

logging.info("{0} tokens skipped.".format(tokens_skipped))
logging.info("{0} tokens replaced.".format(tokens_replaced))

sys.exit(exit_code)