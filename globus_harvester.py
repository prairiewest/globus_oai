"""Globus Harvester.

Usage:
  globus_harvester.py [--onlyharvest | --onlyexport] [--only-new-records] [--export-filepath=<file>] [--export-format=<format>]

Options:
  --onlyharvest             Just harvest new items, do not export anything.
  --onlyexport              Just export existing items, do not harvest anything.
  --only-new-records        Only export records changed since last crawl.
  --export-filepath=<file>  The path to export the data to.
  --export-format=<format>  The export format (gmeta or rifcs).

"""

from docopt import docopt
import json
import os
import time
import configparser

from harvester.OAIRepository import OAIRepository
from harvester.CKANRepository import CKANRepository
from harvester.MarkLogicRepository import MarkLogicRepository
from harvester.CSWRepository import CSWRepository
from harvester.DBInterface import DBInterface
from harvester.HarvestLogger import HarvestLogger
from harvester.TimeFormatter import TimeFormatter
from harvester.Lock import Lock
from harvester.Exporter import Exporter


def get_config_json(repos_json="conf/repos.json"):

	configdict = {}
	with open(repos_json, 'r') as jsonfile:
	    configdict = json.load(jsonfile)

	return configdict


def get_config_ini(config_file="conf/harvester.conf"):
	'''
	Read ini-formatted config file from disk
	:param config_file: Filename of config file
	:return: configparser-style config file
	'''

	config = configparser.ConfigParser()
	config.read(config_file)
	return config


if __name__ == "__main__":

	instance_lock = Lock()
	tstart = time.time()
	arguments = docopt(__doc__)

	config = get_config_ini()
	final_config = {}
	final_config['update_log_after_numitems'] = int(config['harvest'].get('update_log_after_numitems', 1000))
	final_config['abort_after_numerrors']     = int(config['harvest'].get('abort_after_numerrors', 5))
	final_config['record_refresh_days']       = int(config['harvest'].get('record_refresh_days', 30))
	final_config['repo_refresh_days']         = int(config['harvest'].get('repo_refresh_days', 1))
	final_config['temp_filepath']             = config['harvest'].get('temp_filepath', "temp")
	final_config['export_filepath']           = config['export'].get('export_filepath', "data")
	final_config['export_file_limit_mb']      = int(config['export'].get('export_file_limit_mb', 10))
	final_config['export_format']             = config['export'].get('export_format', "gmeta")

	main_log = HarvestLogger(config['logging'])
	main_log.info("Starting... (pid={})".format(os.getpid()))

	dbh = DBInterface(config['db'])
	dbh.setLogger(main_log)

	repo_configs = get_config_json()
	if arguments["--onlyexport"] == False:
	    # Find any new information in the repositories
	    for repoconfig in repo_configs['repos']:
	        if repoconfig['type'] == "oai":
	            repo = OAIRepository(final_config)
	        elif repoconfig['type'] == "ckan":
	            repo = CKANRepository(final_config)
	        elif repoconfig['type'] == "marklogic":
	            repo = MarkLogicRepository(final_config)
	        elif repoconfig['type'] == "csw":
	        	repo = CSWRepository(final_config)
	        repo.setLogger(main_log)
	        if 'copyerrorstoemail' in repoconfig and not repoconfig['copyerrorstoemail']:
	        	main_log.setErrorsToEmail(False)
	        repo.setRepoParams(repoconfig)
	        repo.setDatabase(dbh)
	        repo.crawl()
	        repo.update_stale_records(config['db'])
	        if 'copyerrorstoemail' in repoconfig and not repoconfig['copyerrorstoemail']:
	        	main_log.restoreErrorsToEmail()

	if arguments["--onlyharvest"] == True:
	    raise SystemExit

	if arguments["--export-format"]:
	    final_config['export_format'] = arguments["--export-format"]
	if arguments["--export-filepath"]:
	    final_config['export_filepath'] = arguments["--export-filepath"]

	exporter = Exporter(dbh, main_log, final_config)

	kwargs = {
		"export_format": final_config['export_format'],
		"export_filepath": final_config['export_filepath'],
		"only_new_records": False,
		"temp_filepath": final_config['temp_filepath']
	}
	if arguments["--only-new-records"] == True:
	    kwargs["only_new_records"] = True
	exporter.export_to_file(**kwargs)

	formatter = TimeFormatter()
	main_log.info("Done after {}".format(formatter.humanize(time.time() - tstart)))

	with open("data/last_run_timestamp", "w") as lastrun:
	    lastrun.write(str(time.time()))
	instance_lock.unlock()