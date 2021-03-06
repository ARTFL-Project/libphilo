import os,sys
import hashlib
import struct
import sqlite3
import re
import MetadataQuery
import HitList
import sys
from HitWrapper import HitWrapper
from philologic import Query,shlax

def hit_to_string(hit,width):
    if isinstance(hit,sqlite3.Row):
        hit = hit["philo_id"]
    if isinstance(hit,str):
        hit = [int(x) for x in hit.split(" ")]
    if isinstance(hit,int):
        hit = [hit]
    if len(hit) > width:
        hit = hit[:width]
    pad = width - len(hit)
    hit_string = " ".join(str(h) for h in hit)
    hit_string += "".join(" 0" for n in range(pad))
    return hit_string

class DB:
    def __init__(self,dbpath,width = 7,encoding="utf-8"):
        self.path = dbpath
        self.dbh = sqlite3.connect(dbpath + "/toms.db",width)
        self.dbh.text_factory = str
        self.dbh.row_factory = sqlite3.Row
        self.width = width
        self.encoding="utf-8"
        self.locals = {}
        try:
            execfile(dbpath + "/db.locals.py",globals(),self.locals)
        except IOError:
            pass
        if "metadata_fields" not in self.locals:
            self.locals["metadata_fields"] = ["author","title","date","who","head"]
        if "metadata_hierarchy" not in self.locals:
            self.locals["metadata_hierarchy"] = [ ["author","title","date"],["head"],["who"] ]
        if "metadata_types" not in self.locals:
            self.locals["metadata_types"] = {"author":"doc","title":"doc","date":"doc","head":"div","who":"para"}

    def __getitem__(self,item):
        hit = self.get_id_lowlevel(item)
        hit = [int(x) for x in hit["philo_id"].split(" ")]
        return HitWrapper(hit,self)

    def get_id_lowlevel(self,item):
        hit_s = hit_to_string(item,self.width)
        c = self.dbh.cursor()
        c.execute("SELECT * FROM toms WHERE philo_id=? LIMIT 1;",(hit_s,))
        return c.fetchone()

    def get_all(self,philo_type="doc"):
        """ get all objects of type philo_type """
        hash = hashlib.sha1()
        hash.update(self.path)
        hash.update(philo_type)
        all_hash = hash.hexdigest()
        all_file = "/var/lib/philologic/hitlists/" + all_hash + ".hitlist"
        if not os.path.isfile(all_file):
            #write out the corpus file
            return MetadataQuery.metadata_query(self,all_file,[{"philo_type":['"%s"' % philo_type]}])
        else:
            return HitList.HitList(all_file,0,self)

    def query(self,qs="",method="",method_arg=0,limit=10000000,**metadata):
        """query the PhiloLogic database"""
        hash = hashlib.sha1()
        hash.update(self.path)
        has_metadata = False
        corpus_file = None

        for key,value in metadata.items():
            if isinstance(value,str):
                if value == "":
                    pass
                else:
                    value = [value]
                    metadata[key] = value
            value = [v for v in value if v]
            if value:
                has_metadata = True
                hash.update("%s=%s" % (key,"|".join(value)))

        if has_metadata:
            corpus_hash = hash.hexdigest()
            corpus_file = "/var/lib/philologic/hitlists/" + corpus_hash + ".hitlist"
            corpus_width = 7

            if not os.path.isfile(corpus_file):
                # before we query, we need to figure out what type each parameter belongs to,
                # and sort them into a list of dictionaries, one for each type.
                metadata_dicts = [{} for level in self.locals["metadata_hierarchy"]]
#                print >> sys.stderr, "querying %s" % repr(metadata.items())
                for k,v in metadata.items():
                    for i, params in enumerate(self.locals["metadata_hierarchy"]):
                        if v and (k in params):
                            metadata_dicts[i][k] = v
                            if k in self.locals["metadata_types"]:
                                this_type = self.locals["metadata_types"][k]
                                if this_type == "div":
                                    metadata_dicts[i]["philo_type"] = ['"div"|"div1"|"div2"|"div3"']
                                else:
                                    metadata_dicts[i]["philo_type"] = ['"%s"' % self.locals["metadata_types"][k]]
                metadata_dicts = [d for d in metadata_dicts if d]
                corpus = MetadataQuery.metadata_query(self,corpus_file,metadata_dicts)
            else:
#                print >> sys.stderr, "cached @ %s" % corpus_file
                corpus = HitList.HitList(corpus_file,0,self)
                corpus.finish()             
            print >> sys.stderr, "corpus file of length %d" % len(corpus)
            if len(corpus) == 0:
                return corpus
        else:
            corpus = None
        if qs:
            words_per_hit = len(qs.split(" "))
            hash.update(qs)
            hash.update(method)
            hash.update(str(method_arg))
            hash.update(str(limit))
            search_hash = hash.hexdigest()
            search_file = "/var/lib/philologic/hitlists/" + search_hash + ".hitlist"
            if not os.path.isfile(search_file):
                return Query.query(self,qs,corpus_file,self.width,method,method_arg,limit,filename=search_file)
            else:
                return HitList.HitList(search_file,words_per_hit,self)
        else:
            if corpus:
                return corpus
            else:
                return self.get_all("doc")
