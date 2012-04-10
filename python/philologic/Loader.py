#!/usr/bin/env python
import re
import os
import time
import sys
import codecs
import math
import cPickle
import subprocess
import sqlite3
from ast import literal_eval as eval

from philologic import OHCOVector,SqlToms,Parser
from philologic.LoadFilters import *
from philologic.PostFilters import *
from ExtraFilters import *

sort_by_word = "-k 2,2"
sort_by_id = "-k 3,3n -k 4,4n -k 5,5n -k 6,6n -k 7,7n -k 8,8n -k 9,9n"

blocksize = 2048 # index block size.  Don't alter.
index_cutoff = 10 # index frequency cutoff.  Don't. alter.

## If you are going to change the order of these filters (which is not recommended)
## please consult the documentation for each of these filters in LoadFilters.py
default_filters = [make_word_counts, generate_words_sorted, sorted_toms, prev_next_obj, generate_pages, make_max_id]
default_tables = ['all_toms_sorted', 'all_pages', 'doc_word_counts_sorted']
default_post_filters = [index_metadata_fields]


class Loader(object):

    def __init__(self,workers=4,verbose=True, filters=default_filters, tables=default_tables, extra_tables=False, clean=True):
        self.max_workers = workers 
        self.omax = [0,0,0,0,0,0,0,0,0]
        self.totalcounts = {}
        self.verbose = verbose
        self.filters = filters
        self.tables = tables
        self.extra_tables = extra_tables
        self.clean = clean
        self.sort_by_word = sort_by_word
        self.sort_by_id = sort_by_id
        
    def setup_dir(self,path,files):
        self.destination = path
        self.files = files
        os.mkdir(self.destination)
        self.workdir = self.destination + "/WORK/"
        self.textdir = self.destination + "/TEXT/"
        os.mkdir(self.workdir)
        os.mkdir(self.textdir)

        self.fileinfo =    [{"orig":os.path.abspath(x),
                             "name":os.path.basename(x),
                             "id":n + 1,
                             "newpath":self.textdir + os.path.basename(x),
                             "raw":self.workdir + os.path.basename(x) + ".raw",
                             "words":self.workdir + os.path.basename(x) + ".words.sorted",
                             "toms":self.workdir + os.path.basename(x) + ".toms",
                             "sortedtoms":self.workdir + os.path.basename(x) + ".toms.sorted",
                             "pages":self.workdir + os.path.basename(x) + ".pages",
                             "results":self.workdir + os.path.basename(x) + ".results"} for n,x in enumerate(self.files)]

        for t in self.fileinfo:
            os.system("cp %s %s" % (t["orig"],t["newpath"]))
        
        os.chdir(self.workdir) #questionable
        
    def parse_files(self,xpaths=None,metadata_xpaths=None):
        filequeue = self.fileinfo[:]
        print "%s: parsing %d files." % (time.ctime(),len(filequeue))
        procs = {}
        workers = 0
        done = 0
        total = len(filequeue)
        
        while done < total:
            while filequeue and workers < self.max_workers:
    
                # we want to have up to max_workers processes going at once.
                text = filequeue.pop(0) # parent and child will both know the relevant filenames
                pid = os.fork() # fork returns 0 to the child, the id of the child to the parent.  
                # so pid is true in parent, false in child.
    
                if pid: #the parent process tracks the child 
                    procs[pid] = text["results"] # we need to know where to grab the results from.
                    workers += 1
                    # loops to create up to max_workers children at any one time.
    
                if not pid: # the child process parses then exits.
    
                    i = codecs.open(text["newpath"],"r",)
                    o = codecs.open(text["raw"], "w",) # only print out raw utf-8, so we don't need a codec layer now.
                    print "%s: parsing %d : %s" % (time.ctime(),text["id"],text["name"])
                    parser = Parser.Parser({"filename":text["name"]},text["id"],xpaths=xpaths,metadata_xpaths=metadata_xpaths,output=o)
                    r = parser.parse(i)  
                    i.close()
                    o.close()

                    for f in self.filters:
                        f(self, text)
                    
                    if self.clean:
                        command = 'rm %s' % text['raw']
                        os.system(command)
                    
                    
                    exit()
    
            #if we are at max_workers children, or we're out of texts, the parent waits for any child to exit.
            pid,status = os.waitpid(0,0) # this hangs until any one child finishes.  should check status for problems.
            done += 1 
            workers -= 1
            vec = cPickle.load(open(procs[pid])) #load in the results from the child's parsework() function.
            #print vec
            self.omax = [max(x,y) for x,y in zip(vec,self.omax)]
        print "%s: done parsing" % time.ctime()
    
    def merge_objects(self):
        wordsargs = "sort -m " + sort_by_word + " " + sort_by_id + " " + "*.words.sorted"
#        words_result = open(self.workdir + "all_words_sorted","w")
        print >> sys.stderr, "%s: sorting words" % time.ctime()
#        words_status = subprocess.call(wordargs,0,"sort",stdout=words_result,shell=True)
        words_status = os.system(wordsargs + " > " + self.workdir + "all_words_sorted")
        print >> sys.stderr, "%s: word sort returned %d" % (time.ctime(),words_status)
        if self.clean:
            os.system('rm *.words.sorted')

        tomsargs = "sort -m " + sort_by_id + " " + "*.toms.sorted"
#        toms_result = open(self.workdir + "all_toms_sorted","w")
        print >> sys.stderr, "%s: sorting objects" % time.ctime()
#        toms_status = subprocess.call(tomsargs,0,"sort",stdout=toms_result,shell=True)                                 
        toms_status = os.system(tomsargs + " > " + self.workdir + "all_toms_sorted")
        print >> sys.stderr, "%s: object sort returned %d" % (time.ctime(),toms_status)
        if self.clean:
            os.system('rm *.toms.sorted')
        
        pagesargs = "cat *.pages"
#        pages_result = open(self.workdir + "all_pages","w")
        print >> sys.stderr, "%s: joining pages" % time.ctime()
#        pages_status = subprocess.call(pagesargs,0,"cat",stdout=pages_result,shell=True)
        pages_status = os.system(pagesargs + " > " + self.workdir + "all_pages")
        print >> sys.stderr, "%s: word join returned %d" % (time.ctime(), pages_status)
        
        ## Generate sorted file for word frequencies
        wordsargs = "sort -m " + sort_by_word + " " + sort_by_id + " " + "*.doc.sorted"
        print >> sys.stderr, "%s: sorting words frequencies" % time.ctime()
        words_status = os.system(wordsargs + " > " + self.workdir + "doc_word_counts_sorted")
        print >> sys.stderr, "%s: doc word count frequencies sort returned %d" % (time.ctime(),words_status)

    def analyze(self):
        print self.omax
        vl = [max(int(math.ceil(math.log(float(x),2.0))),1) if x > 0 else 1 for x in self.omax]        
        print vl
        width = sum(x for x in vl)
        print str(width) + " bits wide."
        
        hits_per_block = (blocksize * 8) // width 
        freq1 = index_cutoff
        freq2 = 0
        offset = 0
        
        # unix one-liner for a frequency table
        os.system("cut -f 2 %s | uniq -c | sort -rn -k 1,1> %s" % ( self.workdir + "/all_words_sorted", self.workdir + "/all_frequencies") )
        
        # now scan over the frequency table to figure out how wide (in bits) the frequency fields are, and how large the block file will be.
        for line in open(self.workdir + "/all_frequencies"):    
            f, word = line.rsplit(" ",1) # uniq -c pads output on the left side, so we split on the right.
            f = int(f)    
            if f > freq2:
                freq2 = f
            if f < index_cutoff:
                pass # low-frequency words don't go into the block-mode index.
            else:
                blocks = 1 + f // (hits_per_block + 1) #high frequency words have at least one block.
                offset += blocks * blocksize
        
        # take the log base 2 for the length of the binary representation.
        freq1_l = math.ceil(math.log(float(freq1),2.0))
        freq2_l = math.ceil(math.log(float(freq2),2.0))
        offset_l = math.ceil(math.log(float(offset),2.0))
        
        print "freq1: %d; %d bits" % (freq1,freq1_l)
        print "freq2: %d; %d bits" % (freq2,freq2_l)
        print "offst: %d; %d bits" % (offset,offset_l)
        
        # now write it out in our legacy c-header-like format.  TODO: reasonable format, or ctypes bindings for packer.
        dbs = open(self.workdir + "dbspecs4.h","w")
        print >> dbs, "#define FIELDS 9"
        print >> dbs, "#define TYPE_LENGTH 1"
        print >> dbs, "#define BLK_SIZE " + str(blocksize)
        print >> dbs, "#define FREQ1_LENGTH " + str(freq1_l)
        print >> dbs, "#define FREQ2_LENGTH " + str(freq2_l)
        print >> dbs, "#define OFFST_LENGTH " + str(offset_l)
        print >> dbs, "#define NEGATIVES {0,0,0,0,0,0,0,0,0}"
        print >> dbs, "#define DEPENDENCIES {-1,0,1,2,3,4,5,0,0}"
        print >> dbs, "#define BITLENGTHS {%s}" % ",".join(str(i) for i in vl)
        dbs.close()
        print "%s: analysis done" % time.ctime()
        os.system("pack4 " + self.workdir + "dbspecs4.h < " + self.workdir + "/all_words_sorted")
        print "%s: all indices built. moving into place." % time.ctime()
        os.system("mv index " + self.destination + "/index")
        os.system("mv index.1 " + self.destination + "/index.1") 
        if self.clean:
            os.system('rm all_words_sorted')

    def make_tables(self):
        tables = [('all_toms_sorted', 'toms.db', 'toms'), ('all_pages', 'pages.db', 'toms'),
                  ('doc_word_counts_sorted', 'doc_word_counts.db', 'toms')]
        for file_in, db, table in tables:
            file_in = self.workdir + "/%s" % file_in
            if file_in.endswith('word_counts_sorted'):
                self.toms_table("../toms.db")
                self.word_counts_table(file_in, table, obj_type='doc')
            else:
                self.toms_table("../%s" % db)
                self.make_toms_sql(file_in)
                self.dbh.commit()
            if self.clean:
                os.system('rm %s' % file_in)
        if self.extra_tables:
            for fn in self.extra_tables:
                fn(self)
                
    def toms_table(self, dbfile):
        self.dbh = sqlite3.connect(dbfile)
        self.dbh.text_factory = str
        self.dbh.row_factory = sqlite3.Row
        
    def make_toms_sql(self, file_in):
        known_fields = []
        db = self.dbh
        db.text_factory = str
        db.execute("CREATE TABLE IF NOT EXISTS toms (philo_type,philo_name,philo_id,philo_seq);")
        db.execute("CREATE INDEX type_index ON toms(philo_type);")
        db.execute("CREATE INDEX id_index ON toms(philo_id);")
        s = 0
        for line in open(file_in):
            (philo_type,philo_name,id,attrib) = line.split("\t",3)
            fields = id.split(" ",8)
            if len(fields) == 9: 
                philo_id = " ".join(fields[:7])
                raw_attr = attrib
                #print raw_attr
                r = {}
                r["philo_type"] = philo_type
                r["philo_name"] = philo_name
                r["philo_id"] = philo_id
                r["philo_seq"] = s
                # I should add philo_parent here.  tricky to keep track of though.
                attr = eval(raw_attr)
                #print attr
                for k in attr:
                    if k not in known_fields:
                        db.execute("ALTER TABLE toms ADD COLUMN %s;" % k) 
                        # it seems like i can't safely interpolate column names. ah well.
                        known_fields.append(k)
                    r[k] = attr[k]
                rk = []
                rv = []
                for k,v in r.items():
                    rk.append(k)
                    rv.append(v)
                ks = "(%s)" % ",".join(x for x in rk)
#                print ks
#                print repr(rv)
                insert = "INSERT INTO toms %s values (%s);" % (ks,",".join("?" for i in rv))
                db.execute(insert,rv)
                s += 1
        db.commit()
                
    def word_counts_table(self, file_in, table, obj_type='doc'):
        object_types = ['doc', 'div1', 'div2', 'div3', 'para', 'sent', 'word']
        depth = object_types.index(obj_type) + 1 ## this is for philo_id slices
        
        ## Retrieve column names from toms.db
        original_fields = ['philo_type', 'philo_name', 'philo_id', 'philo_seq', '%s_token_count' % obj_type]
        toms_conn = self.dbh
        toms_c = toms_conn.cursor()
        toms_c.execute('select * from toms')
        extra_fields = [i[0] for i in toms_c.description if i[0] not in original_fields]
        field_list = original_fields + extra_fields + ['bytes']
        
        ## Create table
        conn = sqlite3.connect(self.destination + '/%s_word_counts.db' % obj_type)
        conn.text_factory = str
        c = conn.cursor()
        columns = ','.join(field_list)
        query = 'create table if not exists %s (%s)' % (table, columns)
        c.execute(query)
        c.execute('create index word_index on %s (philo_name)' % table)
        c.execute('create index philo_id_index on %s (philo_id)' % table)
        conn.commit()
        
        sequence = 0
        for line in open(file_in):
            (philo_type,philo_name,id,attrib) = line.split("\t",3)
            philo_id = ' '.join(id.split()[:depth])
            philo_id = philo_id + ' ' + ' '.join('0' for i in range(7 - depth))
            row = {}
            row["philo_type"] = philo_type
            row["philo_name"] = philo_name
            row["philo_id"] = philo_id
            row["philo_seq"] = sequence
            attrib = eval(attrib)
            
            ## Fetch missing fields from toms.db
            toms_query = 'select %s from toms where philo_id=?' % ','.join(extra_fields)
            toms_c.execute(toms_query, (philo_id,))
            results = [i for i in toms_c.fetchone()]
            row.update(dict(zip(extra_fields, results)))
            
            for k in attrib:
                row[k] = attrib[k]
            row_key = []
            row_value = []
            for k,v in row.items():
                row_key.append(k)
                row_value.append(v)
            key_string = "(%s)" % ",".join(x for x in row_key)
            insert = "INSERT INTO toms %s values (%s);" % (key_string,",".join("?" for i in row_value))
            c.execute(insert,row_value)
            sequence += 1       
        conn.commit()

    def finish(self, Philo_Types, Metadata_XPaths, Post_Filters=default_post_filters):
        os.mkdir(self.destination + "/src/")
        os.system("mv dbspecs4.h ../src/dbspecs4.h")
        
        metadata_fields = []
        metadata_hierarchy = []
        metadata_types = {}
        for t in Philo_Types:
            metadata_hierarchy.append([])
            for extractor,path,param in Metadata_XPaths[t]:
                if param not in metadata_fields:
                    metadata_fields.append(param)
                    metadata_hierarchy[-1].append(param)
                if param not in metadata_types:
                    metadata_types[param] = t
        
        ## Create a new all_frequencies file in the frequencies folder
        frequencies = self.destination + '/frequencies'
        os.system('mkdir %s' % frequencies)
        output = open(frequencies + "/word_frequencies", "w")
        for line in open(self.destination + '/WORK/all_frequencies'):
            count, word = tuple(line.split())
            print >> output, word + '\t' + count
        output.close()
        
        ## Create flat files with metadata frequencies
        ## To be replaced by sqlite tables later on
        conn = sqlite3.connect(self.destination + '/toms.db')
        c = conn.cursor()
        for field in metadata_fields:
            query = 'select %s, count(*) from toms group by %s order by count(%s) desc' % (field, field, field)
            try:
                c.execute(query)
                output = open(frequencies + "/%s_frequencies" % field, "w")
                for result in c.fetchall():
                    if result[0] != None:
                        print >> output, result[0].encode('utf-8') + '\t' + str(result[1])
                output.close()
            except sqlite3.OperationalError:
                pass
        conn.close()
        
        db_locals = open(self.destination + "/db.locals.py","w") 

        print >> db_locals, "metadata_fields = %s" % metadata_fields
        print >> db_locals, "metadata_hierarchy = %s" % metadata_hierarchy
        print >> db_locals, "metadata_types = %s" % metadata_types
        print >> db_locals, "db_path = '%s'" % self.destination

        print >> sys.stderr, "wrote metadata info to %s." % (self.destination + "/db.locals.py")
        
        if Post_Filters:
            self.metadata_fields = metadata_fields
            print >> sys.stderr, 'Running the following post-processing filters:'
            for f in Post_Filters:
                print >> sys.stderr, f.__name__ + '...',
                f(self)
                print >> sys.stderr, 'done.'
            
        
        
        

# a quick utility function
def load(path,files,xpaths=None,metadata_xpaths=None,workers=4):
    l = Loader(workers)    
    l.setup_dir(path,files)
    l.parse_files(xpaths,metadata_xpaths)
    l.merge_objects()
    l.analyze()
    l.make_tables()
    l.finish()




        
if __name__ == "__main__":
    os.environ["LC_ALL"] = "C" # Exceedingly important to get uniform sort order.
    os.environ["PYTHONIOENCODING"] = "utf-8"
    
    usage = "usage: philoload.py destination_path texts ..."
    
    try :
        destination = sys.argv[1]
    except IndexError:
        print usage
        exit()
        
    texts = sys.argv[2:]
    if len(sys.argv[2:]) == 0:
        print usage
        exit()

    load(destination,texts)
    
    print "done"
