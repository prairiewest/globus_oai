import os
import time
import sys


class DBInterface:
	def __init__(self, params):
		self.dbtype = params.get('type', None)
		self.dbname = params.get('dbname', None)
		self.host = params.get('host', None)
		self.schema = params.get('schema', None)
		self.user = params.get('user', None)
		self.password = params.get('pass', None)
		self.connection = None
		self.logger = None

		if self.dbtype == "sqlite":
			self.dblayer = __import__('sqlite3')
			con = self.getConnection()
			if os.name == "posix":
				try:
					os.chmod(self.dbname, 0o664)
				except:
					pass

		elif self.dbtype == "postgres":
			self.dblayer = __import__('psycopg2')
			con = self.getConnection()

		else:
			raise ValueError('Database type must be sqlite or postgres in config file')

		with con:
			cur = self.getCursor(con)

			# This table must always exist
			cur.execute("create table if not exists settings (setting_id INTEGER PRIMARY KEY NOT NULL, setting_name TEXT, setting_value TEXT)")

			# Determine if the database schema needs to be updated
			dbversion = self.get_db_version()
			files = os.listdir("sql/" + self.dbtype + "/")
			files.sort()
			for filename in files:
				if '.sql' in filename:
					scriptversion = int(filename.split('.')[0])
					if scriptversion > dbversion:
						# Run this script to update the schema, then record it as done
						with open("sql/" + self.dbtype + "/" + filename, 'r') as scriptfile:
							scriptcontents = scriptfile.read()
						if self.dbtype == "postgres":
							cur.execute(scriptcontents)
						else:
							cur.executescript(scriptcontents)
						self.set_db_version(scriptversion)
						dbversion = scriptversion
						print("Updated database to version: %i" % (scriptversion))


	def setLogger(self, l):
		self.logger = l

	def getConnection(self):
		if self.connection == None:
			if self.dbtype == "sqlite":
				self.connection = self.dblayer.connect(self.dbname)
			elif self.dbtype == "postgres":
				self.connection = self.dblayer.connect("dbname='%s' user='%s' password='%s' host='%s'" % (
					self.dbname, self.user, self.password, self.host))
				self.connection.autocommit = True

		return self.connection

	def getCursor(self, con):
		if self.dbtype == "sqlite":
			con.row_factory = self.getRow()
		cur = con.cursor()
		if self.dbtype == "postgres":
			from psycopg2.extras import RealDictCursor
			cur = con.cursor(cursor_factory=RealDictCursor)

		return cur

	def getRow(self):
		return self.dblayer.Row

	def getType(self):
		return self.dbtype

	def _prep(self, statement):
		if (self.dbtype == "postgres"):
			return statement.replace('?', '%s')
		return statement

	def get_db_version(self):
		dbversion = 0
		con = self.getConnection()
		res = None
		with con:
			cur = self.getCursor(con)
			cur.execute(
				self._prep("select setting_value from settings where setting_name = ? order by setting_value desc"),
				("dbversion",))
			if cur is not None:
				res = cur.fetchone()
			if res is not None:
				dbversion = int(res['setting_value'])

		return dbversion

	def set_db_version(self, v):
		curent_version = self.get_db_version()
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			if curent_version == 0:
				cur.execute(self._prep("insert into settings(setting_value, setting_name) values (?,?)"),
						(v, "dbversion"))
			else:
				cur.execute(self._prep("update settings set setting_value = ? where setting_name = ?"),
						(v, "dbversion"))

	def update_repo(self, **kwargs):
		for key, value in kwargs.items():
			setattr(self, key, value)
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			if self.repo_id > 0:
				# Existing repo
				try:
					self.logger.debug("This repo already exists in the database; updating")
					cur.execute(self._prep("""UPDATE repositories 
						set repository_url=?, repository_set=?, repository_name=?, repository_type=?, repository_thumbnail=?, last_crawl_timestamp=?, item_url_pattern=?,enabled=?,
						abort_after_numerrors=?,max_records_updated_per_run=?,update_log_after_numitems=?,record_refresh_days=?,repo_refresh_days=?
						WHERE repository_id=?"""), (
						self.repo_url, self.repo_set, self.repo_name, self.repo_type, self.repo_thumbnail, time.time(), self.item_url_pattern,
						self.enabled, self.abort_after_numerrors, self.max_records_updated_per_run, self.update_log_after_numitems,
						self.record_refresh_days, self.repo_refresh_days, self.repo_id))
				except self.dblayer.IntegrityError as e:
					# record already present in repo
					self.logger.error("Integrity error in update %s " % (e))
					return self.repo_id
			else:
				# Create new repo record
				try:
					self.logger.debug("This repo does not exist in the database; adding")
					if self.dbtype == "postgres":
						cur.execute(self._prep("""INSERT INTO repositories 
							(repository_url, repository_set, repository_name, repository_type, repository_thumbnail, last_crawl_timestamp, item_url_pattern, enabled,
							abort_after_numerrors,max_records_updated_per_run,update_log_after_numitems,record_refresh_days,repo_refresh_days) 
							VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING repository_id"""), (
							self.repo_url, self.repo_set, self.repo_name, self.repo_type, self.repo_thumbnail, time.time(), self.item_url_pattern,
							self.enabled, self.abort_after_numerrors, self.max_records_updated_per_run, self.update_log_after_numitems,
							self.record_refresh_days, self.repo_refresh_days))
						cur.execute("SELECT CURRVAL('repositories_id_sequence')")
						res = cur.fetchone()
						repo_id = int(res['currval'])

					if self.dbtype == "sqlite":
						cur.execute(self._prep("""INSERT INTO repositories 
							(repository_url, repository_set, repository_name, repository_type, repository_thumbnail, last_crawl_timestamp, item_url_pattern, enabled,
							abort_after_numerrors,max_records_updated_per_run,update_log_after_numitems,record_refresh_days,repo_refresh_days) 
							VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"""), (
							self.repo_url, self.repo_set, self.repo_name, self.repo_type, self.repo_thumbnail, time.time(), self.item_url_pattern,
							self.enabled, self.abort_after_numerrors, self.max_records_updated_per_run, self.update_log_after_numitems,
							self.record_refresh_days, self.repo_refresh_days))
						self.repo_id = int(cur.lastrowid)

				except self.dblayer.IntegrityError as e:
					self.logger.error("Cannot add repository: %s" % (e))

		return self.repo_id

	def get_repo_id(self, repo_url, repo_set):
		returnvalue = 0
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			cur.execute(
				self._prep("select repository_id from repositories where repository_url = ? and repository_set = ?"),
				(repo_url, repo_set))
			if cur is not None:
				records = cur.fetchall()
			else:
				return 0
			for record in records:
				returnvalue = int(record['repository_id'])
				
		return returnvalue

	def get_repo_last_crawl(self, repo_id):
		returnvalue = 0
		if repo_id == 0 or repo_id is None:
			return 0
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			cur.execute(self._prep("select last_crawl_timestamp from repositories where repository_id = ?"), (repo_id,))
			if cur is not None:
				records = cur.fetchall()
			else:
				return 0
			for record in records:
				returnvalue = int(record['last_crawl_timestamp'])

		self.logger.debug("Last crawl ts for repo_id %s is %s" % (repo_id, returnvalue))
		return returnvalue

	def get_domain_schema_id(self, namespace):
		returnvalue = 0
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			cur.execute(self._prep("select schema_id from domain_schemas where namespace = ?"), (namespace,))
			if cur is not None:
				records = cur.fetchall()
			else:
				return 0
			for record in records:
				returnvalue = int(record['schema_id'])

		return returnvalue

	def create_domain_schema(self, namespace):
		con = self.getConnection()
		schema_id = self.get_domain_schema_id(namespace)
		with con:
			cur = self.getCursor(con)
			# Create new domain_schema record
			try:
				if self.dbtype == "postgres":
					cur.execute(self._prep("""INSERT INTO domain_schemas (namespace) VALUES (?) RETURNING schema_id"""),
								(namespace,))
					res = cur.fetchone()
					schema_id = int(res[0])

				if self.dbtype == "sqlite":
					cur.execute(self._prep("""INSERT INTO domain_schemas (namespace) VALUES (?)"""), (namespace,))
					schema_id = int(cur.lastrowid)

			except self.dblayer.IntegrityError as e:
				# record already present in repo
				self.logger.error("Error creating domain schema: %s " % (e))
				return schema_id

		return schema_id

	def update_last_crawl(self, repo_id):
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			cur.execute(self._prep("update repositories set last_crawl_timestamp = ? where repository_id = ?"),
						(int(time.time()), repo_id))

	def delete_record(self, record):
		con = self.getConnection()
		if record['record_id'] == 0:
			return False
		with con:
			cur = self.getCursor(con)

			try:
				cur.execute(self._prep("UPDATE records set deleted = 1, modified_timestamp = ? where record_id=?"),
							(time.time(), record['record_id']))
			except:
				self.logger.error("Unable to mark as deleted record %s" % (record['local_identifier'],))
				return False

			try:
				cur.execute(self._prep("DELETE from creators where record_id=?"), (record['record_id'],))
				cur.execute(self._prep("DELETE from subjects where record_id=?"), (record['record_id'],))
				cur.execute(self._prep("DELETE from rights where record_id=?"), (record['record_id'],))
				cur.execute(self._prep("DELETE from descriptions where record_id=?"), (record['record_id'],))
				cur.execute(self._prep("DELETE from tags where record_id=?"), (record['record_id'],))
				cur.execute(self._prep("DELETE from geospatial where record_id=?"), (record['record_id'],))
				cur.execute(self._prep("DELETE from domain_metadata where record_id=?"), (record['record_id'],))
				cur.execute(self._prep("DELETE from access where record_id=?"), (record['record_id'],))
			except:
				self.logger.error("Unable to delete related table rows for record %s" % (record['local_identifier'],))
				return False

		self.logger.debug("Marked as deleted: record %s" % (record['local_identifier'],))
		return True

	def get_record_id(self, repo_id, local_identifier):
		returnvalue = None
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			cur.execute(self._prep("select record_id from records where local_identifier=? and repository_id = ?"),
						(local_identifier, repo_id))
			if cur is not None:
				records = cur.fetchall()
			else:
				return None
			for record in records:
				returnvalue = int(record['record_id'])

		return returnvalue

	def write_record(self, record, repo_id, metadata_prefix, domain_metadata):
		if record == None:
			return None
		record["record_id"] = self.get_record_id(repo_id, record["identifier"])

		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			source_url = ""
			if 'dc:source' in record:
				if isinstance(record["dc:source"], list):
					source_url = record["dc:source"][0]
				else:
					source_url = record["dc:source"]

			if record["record_id"] is None:
				try:
					if self.dbtype == "postgres":
						cur.execute(self._prep(
							"INSERT INTO records (title, pub_date, contact, series, modified_timestamp, source_url, deleted, local_identifier, repository_id) VALUES(?,?,?,?,?,?,?,?,?) RETURNING record_id"),
							(record["title"], record["pub_date"], record["contact"], record["series"],
							 time.time(), source_url, 0, record["identifier"], repo_id))
						cur.execute("SELECT CURRVAL('records_id_sequence')")
						res = cur.fetchone()
						record_id = int(res[0])
						record["record_id"] = record_id
					if self.dbtype == "sqlite":
						cur.execute(self._prep(
							"INSERT INTO records (title, pub_date, contact, series, modified_timestamp, source_url, deleted, local_identifier, repository_id) VALUES(?,?,?,?,?,?,?,?,?)"),
							(record["title"], record["pub_date"], record["contact"], record["series"],
							 time.time(), source_url, 0, record["identifier"], repo_id))
						record["record_id"] = int(cur.lastrowid)
				except self.dblayer.IntegrityError as e:
					self.logger.error("Record insertion problem: %s" %e)
					return None
			else:
				cur.execute(self._prep(
					"UPDATE records set title=?, pub_date=?, contact=?, series=?, modified_timestamp=?, source_url=?, deleted=?, local_identifier=? WHERE record_id = ?"),
					(record["title"], record["pub_date"], record["contact"], record["series"], time.time(),
					 source_url, 0, record["identifier"], record["record_id"]))

			if record["record_id"] is None:
				return None

			if "creator" in record:
				try:
					# TODO: figure out a cleaner way to remove related table data other than just purging it all each time
					cur.execute(self._prep("DELETE from creators where record_id = ? and is_contributor=0"),
								(record["record_id"],))
				except:
					pass
				if not isinstance(record["creator"], list):
					record["creator"] = [record["creator"]]
				for creator in record["creator"]:
					try:
						cur.execute(
							self._prep("INSERT INTO creators (record_id, creator, is_contributor) VALUES (?,?,?)"),
							(record["record_id"], creator, 0))
					except self.dblayer.IntegrityError as e:
						self.logger.error("Record insertion problem: %s" %e)
						pass

			if "contributor" in record:
				try:
					cur.execute(self._prep("DELETE from creators where record_id = ? and is_contributor=1"),
								(record["record_id"],))
				except:
					pass
				if not isinstance(record["contributor"], list):
					record["contributor"] = [record["contributor"]]
				for creator in record["contributor"]:
					try:
						cur.execute(
							self._prep("INSERT INTO creators (record_id, creator, is_contributor) VALUES (?,?,?)"),
							(record["record_id"], creator, 1))
					except self.dblayer.IntegrityError as e:
						self.logger.error("Record insertion problem: %s" %e)
						pass

			if "subject" in record:
				try:
					cur.execute(self._prep("DELETE from subjects where record_id = ?"), (record["record_id"],))
				except:
					pass
				if not isinstance(record["subject"], list):
					record["subject"] = [record["subject"]]
				for subject in record["subject"]:
					if (subject == "form_descriptors"):
						continue
					try:
						if subject is not None and len(subject) > 0:
							cur.execute(self._prep("INSERT INTO subjects (record_id, subject) VALUES (?,?)"),
										(record["record_id"], subject))
					except self.dblayer.IntegrityError as e:
						self.logger.error("Record insertion problem: %s" %e)
						pass

			if "publisher" in record:
				try:
					cur.execute(self._prep("DELETE from publishers where record_id = ?"), (record["record_id"],))
				except:
					pass
				if not isinstance(record["publisher"], list):
					record["publisher"] = [record["publisher"]]
				for publisher in record["publisher"]:
					try:
						if publisher is not None and len(publisher) > 0:
							cur.execute(self._prep("INSERT INTO publishers (record_id, publisher) VALUES (?,?)"),
										(record["record_id"], publisher))
					except self.dblayer.IntegrityError as e:
						self.logger.error("Record insertion problem: %s" %e)
						pass

			if "rights" in record:
				try:
					cur.execute(self._prep("DELETE from rights where record_id = ?"), (record["record_id"],))
				except:
					pass
				if not isinstance(record["rights"], list):
					record["rights"] = [record["rights"]]
				for rights in record["rights"]:
					try:
						cur.execute(self._prep("INSERT INTO rights (record_id, rights) VALUES (?,?)"),
									(record["record_id"], rights))
					except self.dblayer.IntegrityError:
						pass

			if "description" in record:
				try:
					cur.execute(self._prep("DELETE from descriptions where record_id = ? and language='en' "),
								(record["record_id"],))
				except:
					pass
				if not isinstance(record["description"], list):
					record["description"] = [record["description"]]
				for description in record["description"]:
					try:
						cur.execute(
							self._prep("INSERT INTO descriptions (record_id, description, language) VALUES (?,?,?)"),
							(record["record_id"], description, 'en'))
					except self.dblayer.IntegrityError:
						pass

			if "description_fr" in record:
				try:
					cur.execute(self._prep("DELETE from descriptions where record_id = ? and language='fr' "),
								(record["record_id"],))
				except:
					pass
				if not isinstance(record["description_fr"], list):
					record["description_fr"] = [record["description_fr"]]
				for description_fr in record["description_fr"]:
					try:
						cur.execute(
							self._prep("INSERT INTO descriptions (record_id, description, language) VALUES (?,?,?)"),
							(record["record_id"], description_fr, 'fr'))
					except self.dblayer.IntegrityError:
						pass

			if "tags" in record:
				try:
					cur.execute(self._prep("DELETE from tags where record_id = ? and language='en' "),
								(record["record_id"],))
				except:
					pass
				if not isinstance(record["tags"], list):
					record["tags"] = [record["tags"]]
				for tag in record["tags"]:
					try:
						cur.execute(self._prep("INSERT INTO tags (record_id, tag, language) VALUES (?,?,?)"),
									(record["record_id"], tag, "en"))
					except self.dblayer.IntegrityError:
						pass

			if "tags_fr" in record:
				try:
					cur.execute(self._prep("DELETE from tags where record_id = ? and language='fr' "),
								(record["record_id"],))
				except:
					pass
				if not isinstance(record["tags_fr"], list):
					record["tags_fr"] = [record["tags_fr"]]
				for tag_fr in record["tags_fr"]:
					try:
						cur.execute(self._prep("INSERT INTO tags (record_id, tag, language) VALUES (?,?,?)"),
									(record["record_id"], tag_fr, "fr"))
					except self.dblayer.IntegrityError:
						pass

			if "geospatial" in record:
				try:
					cur.execute(self._prep("DELETE from geospatial where record_id = ?"), (record["record_id"],))
				except:
					pass
				for coordinates in record["geospatial"]["coordinates"][0]:
					try:
						cur.execute(self._prep(
							"INSERT INTO geospatial (record_id, coordinate_type, lat, lon) VALUES (?,?,?,?)"),
							(record["record_id"], record["geospatial"]["type"], coordinates[0], coordinates[1]))
					except self.dblayer.IntegrityError:
						pass

			if "access" in record:
				try:
					cur.execute(self._prep("DELETE from access where record_id = ?"), (record["record_id"],))
				except:
					pass
				if not isinstance(record["access"], list):
					record["access"] = [record["access"]]
				for access in record["access"]:
					try:
						cur.execute(self._prep("INSERT INTO access (record_id, access) VALUES (?,?)"),
									(record["record_id"], access))
					except self.dblayer.IntegrityError:
						pass

			if len(domain_metadata) > 0:
				try:
					cur.execute(self._prep("DELETE from domain_metadata where record_id = ?"), (record["record_id"],))
				except:
					pass
				for field_uri in domain_metadata:
					field_pieces = field_uri.split("#")
					domain_schema = field_pieces[0]
					field_name = field_pieces[1]
					schema_id = self.get_domain_schema_id(domain_schema)
					if (schema_id == 0):
						schema_id = self.create_domain_schema(domain_schema)
					if not isinstance(domain_metadata[field_uri], list):
						domain_metadata[field_uri] = [domain_metadata[field_uri]]
					for field_value in domain_metadata[field_uri]:
						try:
							cur.execute(self._prep(
								"INSERT INTO domain_metadata (record_id, schema_id, field_name, field_value) VALUES (?,?,?,?)"),
								(record["record_id"], schema_id, field_name, field_value))
						except self.dblayer.IntegrityError:
							pass

		return None

	def get_stale_records(self, stale_timestamp, repo_id, max_records_updated_per_run):
		con = self.getConnection()
		records = []
		with con:
			cur = self.getCursor(con)
			cur.execute(self._prep("""SELECT recs.record_id, recs.title, recs.pub_date, recs.contact, recs.series, recs.modified_timestamp, recs.local_identifier, 
				repos.repository_id, repos.repository_type
				FROM records recs, repositories repos
				where recs.repository_id = repos.repository_id and recs.modified_timestamp < ? and repos.repository_id = ?
				LIMIT ?"""), (stale_timestamp, repo_id, max_records_updated_per_run))
			if cur is not None:
				records = cur.fetchall()

		return records

	def touch_record(self, record):
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)
			try:
				cur.execute(self._prep("UPDATE records set modified_timestamp = ? where record_id = ?"),
							(time.time(), record['record_id']))
			except:
				self.logger.error("Unable to update modified_timestamp for record id %s" % (record['record_id'],))
				return False

		return True

	def write_header(self, local_identifier, repo_id):
		con = self.getConnection()
		with con:
			cur = self.getCursor(con)

			try:
				cur.execute(self._prep(
					"INSERT INTO records (title, pub_date, contact, series, modified_timestamp, local_identifier, repository_id) VALUES(?,?,?,?,?,?,?)"),
					("", "", "", "", 0, local_identifier, repo_id))
			except self.dblayer.IntegrityError as e:
				# record already present in repo
				self.logger.error("Error creating record header: %s " % (e))
				return None

		return None
