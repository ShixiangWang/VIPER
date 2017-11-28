#!/usr/bin/env python
"""
Copyright 2014 Len Taing

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
-------------------------------------------------------------------------------
UPDATED 2016-10-13: ported to python3 AND to split the input into 
_exon.bed, _promoter.bed, etc.
-------------------------------------------------------------------------------
UPDATE: 2017-11-28: modifying it to use as a virusseq annotator
-------------------------------------------------------------------------------
A program to annotate RSEM output transcripts with the transcript location

OUTPUT: each line of the original RSEM file but with a chr,start,end added as 
3 extra cols
"""
import os
import sys
from optparse import OptionParser

import bisect

def inRegion(reg, site):
    """given a region tuple, (start, end) 
    returns True if site is >= start <= end"""
    return site >= reg[0] and site <= reg[1]

#HACK- map gene_ids to (chr,start,end)
gene_to_loc_map={}

class Gene():
    """Gene object--will help us store gene information and perform some fns"""
    #should make these command line parameters!
    upstream = 2000 #promoter = 2kb upstream of TSS
    downstream = 0 #gene ends at TTS

    def __init__(self, line):
        """Given a line/row from the UCSC geneTable, grab: 
        name, name2, chrom, strand, txStart, txEnd, cdsStart, cdsEnd, exons
        NOTE: refGenes locations are oriented according to the 5' orientation
        ensuring that *Start will always be < *End even though the semantics
        are reversed for - strand genes. 
        **WE will keep this 5' orientation**
        """
        tmp = line.strip().split("\t")
        attribs = dict([a.split() for a in tmp[-1].strip().split(";")])
        self.chrom = tmp[0]
        self.txStart = int(tmp[3])
        self.txEnd = int(tmp[4])
        self.strand = tmp[6] #can only be "+" or "-"
        self.name = eval(attribs["gene_id"]) #eval b/c quotes are in string
        self.name2 = eval(attribs["transcript_id"])

        gene_to_loc_map[self.name] = (self.chrom, self.txStart, self.txEnd)


        #DROP
        #self.cdsStart = int(tmp[6])
        #self.cdsEnd = int(tmp[7])
        #exStarts = [int(i) for i in tmp[9].split(",") if i]
        #exEnds = [int(i) for i in tmp[10].split(",") if i]
        #self.exons = zip(exStarts, exEnds)

    def chunk(self):
        """a method that will return the start and end sites of the gene,
        e.g. the 'chunk' of chromosome it occupies.
        NOTE: accounts for promoter region, which uses the upstream!
        returns (start, end)

        this is used to see if a site falls within a gene 'chunk'
        """
        if self.strand == '+':
            #check for negatives?
            return (self.txStart - Gene.upstream, self.txEnd + Gene.downstream)
        else: #negative strand
            #check for negative?
            return (self.txStart - Gene.downstream, self.txEnd + Gene.upstream)
    
    def siteInGene(self, site):
        """Given a site, e.g. 5246835, returns True if the site falls within
        the gene chunk, else False
        """
        c = self.chunk()
        #return site >= c[0] and site <= c[1]
        return inRegion(c, site)

    def classifySite(self, site):
        """Given a site, returns 
        "Intergenic" if it is OUTSIDE of gene--
        NOTE: since we don't know about other genes, "Intergenic" might not 
        be the true classification of the site

        "Promoter" if it is in upstream(2kb) - TSS
        "Exon" if it is in one of the exon regions
        "Intron" otherwise
        """
        def inPromoter(s):
            #VERSION 1-WHERE 5'UTR is NOT considered in promoter
            if self.strand == "+":
                p = (self.txStart - Gene.upstream, self.txStart) 
            else:
                p = (self.txEnd, self.txEnd + Gene.upstream)
            
            #VERSION 2- Where 5'UTR is in promoter
            #if self.strand == "+":
            #    p = (self.txStart - Gene.upstream, self.cdsStart) 
            #else:
            #    p = (self.cdsEnd, self.txEnd + Gene.upstream)

            #return s >= p[0] and s <= p[1]
            return inRegion(p, s)

        def inExons(s):
            for e in self.exons:
                #if s >= e[0] and s <= e[1]:
                if inRegion(e, s):
                    return True
            return False

        if not self.siteInGene(site):  ## discuss with len 201486
            return "Intergenic"
        elif inPromoter(site):
            return "Promoter"
        elif inExons(site):
            return "Exon"
        else:
            return "Intron"

    def __str__(self):        
        ls = ["Gene: %s\%s" % (self.name,self.name2),
              "Loc: %s:%s-%s" % (self.chrom, self.txStart, self.txEnd),
              "Strand: %s" % self.strand,
              "Coding: %s-%s" % (self.cdsStart,self.cdsEnd),
              "Exons: %s" % self.exons]
        return "\n".join(ls)

    #Comparisons based on genomic location--assumming other is on same chr
    def __eq__(self, other):
        return self.chunk() == other.chunk()
    def __ne__(self, other):
        return self.chunk() == other.chunk()  ## discuss with len 201486
    #order by chunk()[0]s
    def __lt__(self, other):
        return self.chunk()[0] < other.chunk()[0]
    def __le__(self, other):
        return self.chunk()[0] <= other.chunk()[0]
    def __gt__(self, other):
        """order by chunk()[0]s-Return true if self is DOWNSTREAM from other"""
        return self.chunk()[0] > other.chunk()[0]
    def __ge__(self, other):
        return self.chunk()[0] >= other.chunk()[0]

class Chromosome(list):
    """list of SORTED Gene objects (sorted by gene.chunk()[0])"""
    def __init__(self, *args):
        list.__init__(self, *args)

    def add(self, gene):
        """adds the gene into the sorted list"""
        i = bisect.bisect(self, gene)
        self[i:i] = [gene]

    def len(self):
        return len(self)

    def findGene(self, site, lo, hi):
        """Given a site, e.g. 5246835, will return the gene chunk that the site
        falls into, otherwise None"""
        #binary search
        #if hi < lo or lo >= self.len or hi < 0: ## need discuss with len 201486
        if hi < lo or lo >= len(self) or hi < 0: ## need discuss with len 201486
            return None
        else:
            mid = int((hi + lo)/2)
            #print self[mid]
            #print hi
            #print lo
            if self[mid].siteInGene(site): #Found!
                return self[mid]
            else:
                if self[mid].chunk()[0] < site:
                    return self.findGene(site, mid+1, hi)
                else:
                    return self.findGene(site, lo, mid-1)

def main():
    optparser = OptionParser()
    optparser.add_option("-g", "--gt", help="UCSC geneTable")
    optparser.add_option("-b", "--bed", help="bed file (of genomic sites)")
    optparser.add_option("-n", "--basename", help="basename for the output (default: derived from bed file")
    optparser.add_option("-o", "--outpath", help="output path", default="./")
    optparser.add_option("-u", "--up", help="How many bps should we consider upstream of TSS? default: 0", default=0)
    optparser.add_option("-d", "--down", help="How many bps should we consider downstream of TTS? default: 0", default=0)
    optparser.add_option("-e", "--exon", help="How many bps should we consider downstream of TTS? default: 0", default=0)
    optparser.add_option("-t", "--gene", help="How many bps should we consider downstream of TTS? default: 0", default=0)

    (options, args) = optparser.parse_args(sys.argv)

    Gene.upstream = int(options.up)
    Gene.downstream = int(options.down)

    if not options.gt or not options.bed:
        print("USAGE: bedAnnotate.py -g [UCSC geneTable] -b [bed file of genomic sites] -u [upstream of TSS- default:0 (optional)] -d [downstream of TTS- default:0 (optional)]")
        sys.exit(-1)

    #l = "625	NM_000518	chr11	-	5246695	5248301	5246827	5248251	3	5246695,5247806,5248159,	5246956,5248029,5248301,	0	HBB	cmpl	cmpl	0,2,0,"
    outpath = options.outpath

    #read the genetable
    f = open(options.gt)
    genome = {}
    for l in f:
        if l.startswith("#"):
            continue
        g = Gene(l)
        if g.chrom not in genome:
            genome[g.chrom] = Chromosome()
        genome[g.chrom].add(g)
    f.close()

    #output files
    if options.basename:
        baseName = options.basename
    else: #derive the basename--using the filename of the bedfile--drop last
        baseName = ".".join(options.bed.split("/")[-1].split(".")[:-1])

    f = open(options.bed)
    #header
    hdr = f.readline().strip().split("\t")
    hdr.extend(["Chrom","Start","End"])
    print("\t".join(hdr))
    for l in f:
        #note: just taking chr and start info, i.e. col0 and col1
        tmp = l.strip().split("\t")
        gene_id = tmp[0]
        gene_loc = [".",".","."] #set to undefined
        if gene_id in gene_to_loc_map:
            gene_loc = list(gene_to_loc_map[gene_id])
        tmp.extend(gene_loc)
        #convert all elms in tmp to str
        out = "\t".join([str(a) for a in tmp])
        print(out)

if __name__=='__main__':
    main()

