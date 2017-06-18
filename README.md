Gitbib
======

 - Version control your references
 - Auto-fetch relevant bibliographic data
 - Render as pretty html or `.bib`
 
[Example](https://htmlpreview.github.io/?https://raw.githubusercontent.com/mpharrigan/gitbib/master/example/gitbib/all.html)
output.

![Example](https://github.com/mpharrigan/gitbib/raw/master/example/screenshot.png)
 
Version control
---------------
  
Pick a paper, come up with a meaningful identifier, attach
a doi or arxiv id, and save in a yaml file:

```yaml
2015-mdtraj:
  doi: 10.1016/j.bpj.2015.08.015
  
2009-theobald-rmsd:
  doi: 10.1002/jcc.21439
```

You can easily version control this file.


Description and tags
--------------------

You might want to add some tags:

```yaml
2015-mdtraj:
  doi: 10.1016/j.bpj.2015.08.015
  tags: [molecular-dynamics, analysis, python]

2009-theobald-rmsd:
  doi: 10.1002/jcc.21439
  tags: [molecular-dynamics, analysis, algorithm]
```

And descriptions:

```yaml
2015-mdtraj:
  doi: 10.1016/j.bpj.2015.08.015
  description: "MDTraj loads every trajectory format!"

2009-theobald-rmsd:
  doi: 10.1002/jcc.21439
  description: "Fast method for computing RMSD!"
```

Cross-references are a powerful tool to give context to papers.

```yaml
2015-mdtraj:
  doi: 10.1016/j.bpj.2015.08.015
  description: |+
    MDTraj loads every trajectory format! It computes
    RMSD pretty fast using [2009-theobald-rmsd].

2009-theobald-rmsd:
  doi: 10.1002/jcc.21439
```

Contextualize the work by noting important references
from the paper (with their reference number)

```yaml
2015-mdtraj:
  doi: 10.1016/j.bpj.2015.08.015
  description: |+
    MDTraj loads every trajectory format!     
    The authors justify their work by noting that
    [2013-milliseconds-folding=2] claims analysis 
    is becoming the bottleneck for MD.
    
2013-milliseconds-folding:
  doi: 10.1016/j.sbi.2012.11.002
```

Bibliography data fetching
--------------------------

Relevant bibliographic data is automatically
fetched using crossref or arxiv. There is no
need for you to manually fill in authors, title,
etc. Gitbib will cache this metadata to avoid
flooding these services with requests.


Installation
------------

Clone this repository. Install the program's runtime
and installation requirements, resp.

    pip install -r requirements.txt
    pip install flit
    
Install the package with flit

    flit install


Usage
-----

Gitbib expects a directory full of YAML files containing
references as well as a file named `gitbib.yaml`, which specifies
configuration options. See `example/gitbib.yaml` for a commented
template of what to put in this file.

Pass the directory containing references and `gitbib.yaml` to the
command-line program `gitbib`.
You can build the example references by going
to the `example/` folder in this repository and running gitbib.

    cd example/
    gitbib ./
    
This will generate html pages and `bib` files for each output
specified in `gitbib.yaml` as well as an `index.html` file to
browse through the outputs.

Details
-------

### Description syntax

The description field uses some markdown-style formatting.
Paragraph breaks are indicated with blank lines. Otherwise,
duplicated whitespace is trimmed.

You can include `[links](github.com)` like that.

I'm very-much interested in crossreferencing entries.
If the entry cites another entry as reference e.g. 23, 
link it like

    They cite the [2011-prinz=23] review
    
Otherwise, crossreference like

    This is cited by the [2011-prinz] review
    
See how important good identifiers are!
    

### Misc

 - identifier: The key (identifier) must be unique across all input `yaml` files.
   I like all-lowercase, hyphen-spaced identifiers starting
   with the year, optionally middling with the first author's
   last name (if necessary to distinguish), and ending with
   a short description of what the paper is about.
 - identifier: Right now, we support `doi` and `arxiv`.
