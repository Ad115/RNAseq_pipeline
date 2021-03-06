#! /bin/env python3

"""
Mapping the RNAseq data with HISAT2.
=====================================

Author: Andrés García García @ May 2018

About the project
-----------------
We are trying to detect if there are changes in the expression of
long non-coding RNAs between the left and right hemisphere of a mouse's
brain (telencephalon). For this, 3 samples where taken and sequenced using
RNAseq. For more information about RNAseq, see: 
https://galaxyproject.org/tutorials/rb_rnaseq/


The data
--------

NOTE: This is the third step of the pipeline, the first ones where 
checking the quality of the reads and trimming them.

The data belongs to Dr. Alfredo Varela Echávarri and comes
from telencephalus tissue extracted by Brenda (INB Lab A03). 

The data is in the form of FASTQ files in the 'data' folder.

The analysis
------------

The current script represents the third part of the analysis pipeline, the
mapping of the reads to the genome (Mus musculus). 

As there are many samples and many paired read files, this script automates
the process of doing the mapping for all the files and the data.

The mapping is done using HISAT2, the successor of TOPHAT2. For this, we
downloaded the pre-built HGFM index for reference plus SNPs and transcripts
from the link on the official HISAT2 page 
(ftp://ftp.ccb.jhu.edu/pub/infphilo/hisat2/data/grcm38_snp_tran.tar.gz).

We are basing our protocol on the instructions provided in:
https://davetang.org/muse/2017/10/25/getting-started-hisat-stringtie-ballgown/
So we are executing:
    hisat2 -p 8 --dta -x <index folder with prefix> -1 <sample1> -2 <sample2> -S <outputfile.sam>

Procedure
---------
To map the files pair by pair would be terribly slow, so we are trying to 
paralelize as much as we can.

The present script first gets the names of the files to map, finding paired and
unpaired files. Then, the command to be executed is assembled for each mapping process
and a new script is assembled and executed that kickstarts the paralell jobs.

Why do we need an additional script? Well, in SGE, the number of jobs in a job array
must be specified in advance, but it's only at runtime when we know how many jobs we'll use. So
we need to invoke another process to perform the task. The generated script is saved
for debugging and repeatability purposes.


Note for the developer or maintainer
------------------------------------
This script relies heavily on the use of pathlib.Path objects, present in the Python
standard library. Also on generator functions and on the use of the subprocess 'run' and 
'check_output' functions.

"""

import re
import click
import textwrap
import subprocess
from typing import Union, List, Iterable, Generator
from itertools import chain
from pathlib import Path


def get_output(command: Union[str, List[str]], **kwargs) -> str:
    """Execute a command through the shell, get the output as a string.
    """
    if isinstance(command, str) and not kwargs.get('shell'):
        command = command.split()
    bytes_output = subprocess.check_output(command, **kwargs)
    return bytes_output.decode('UTF-8')
# ---

def run(command: Union[str, List[str]], **kwargs) -> subprocess.CompletedProcess:
    """Execute a command through the shell. Doesn't capture output.
    """
    if isinstance(command, str) and not kwargs.get('shell'):
        command = command.split()
    return subprocess.run(command, **kwargs)
# ---

def find_paired(dir: Union[str, Path]):
    """Get pairs of sequence files.
    
    Search the given directory for pairs of fastq files,
    return an iterator on pairs of sequence file names. 
    """
    R1 = dir.glob('*R1_paired*')
    R2 = dir.glob('*R2_paired*')
    
    return zip(sorted(str(f) for f in R1), 
               sorted(str(f) for f in R2))
# ---

def find_unpaired(dir: Union[str, Path], 
                  already_paired: Iterable[str]) -> List[str]:
    """Get unpaired sequence files.
    
    Search the given directory for unpaired FASTQ files.
    """
    already_paired = set(already_paired)
    
    return [str(f) 
                for f in dir.glob('*trimmed.fastq') 
                if str(f) not in already_paired]
# ---

def search_files(data_path: Union[str, Path]):
    """Search for the data files for each sample.
    
    Input: The path to the data folder (as pathlib.Path object).
    
    Assumes the data folder has the following structure:
    
        data/ (<-- data_path points here)
            │
            ├── mm<SAMPLE NO.>X.fastq (several files)
            ├── mm3R_XXXXXX_XXXX_X1_###.fastq (several files)
            └── mm3R_XXXXXX_XXXX_X2_###.fastq (several files)
    
    """
    pairs = list(find_paired(data_path))
    loners = find_unpaired(
                    data_path, 
                    already_paired=chain.from_iterable(pairs))
    
    return {'paired': pairs,
            'unpaired': loners}
# ---

def assemble_commands(files, 
                      idx_prefix: Union[str, Path], 
                      output_path: Union[str, Path]) -> Generator[str, None, None]:
    """Assemble the mapping commands.
    
    Input:
        samples: A dictionary with the RNAseq files location and pairing information
                 as returned from the 'search_files' function.
        idx_prefix: A string with the path and file prefix for the genome index.
        output_path: A valid pathlib.Path object pointing to the output directory.
    
    Generates the commands that would be executed to make the map.
    
    The mapping is done using the following commands
        For paired reads:
            hisat2 --dta -x <index folder with prefix> -1 <pair1> -2 <pair2> -S <outputfile.sam>
        For unpaired reads:
            hisat2 --dta -x <index folder with prefix> -U <unpaired> -S <outputfile.sam>
    """
    output_path = Path(output_path)
    
    # Unpaired reads
    loners = files['unpaired']

    for unpaired_f in loners:
           
        out_filename = re.sub('fastq$','sam', Path(unpaired_f).name)
        S = str(output_path / out_filename)

        yield f'hisat2 --dta -x {idx_prefix} -U {unpaired_f} -S {S}'
        
    # Paired reads
    pairs = files['paired']

    for p1, p2 in pairs:
            
        out_filename = re.sub('_R[12]_', '_', Path(p1).name)
        out_filename = re.sub('fastq$', 'sam', out_filename)

        S = str(output_path / out_filename) # The / is for appending to the path object.

        yield f'hisat2 --dta -x {idx_prefix} -1 {p1} -2 {p2} -S {S}'
# ---

#### <<<<<< MAIN PROCEDURE >>>>>>> ####

# Command line interface
@click.command()

@click.option('--input_dir', '-i',
              help='The directory where the input files reside.'
                   ' Default "./trimmed".')

@click.option('--output_dir', '-o',
              help='The directory where to output the results.'
                   ' Default "./mapped".')

@click.option('--idx_prefix', '-p',
              help='The prefix of the genome index files.'
                   ' Default "./index/grcm38_snp_tran/genome_snp_tran".')

@click.option('--ram', '-r', 
              help='RAM amount per job (in Gb). Default 8.')
    
def main(input_dir, output_dir, idx_prefix, ram):
    """Assemble the script with the commands for trimming and submit (qsub) it."""
    
    input_dir = Path(input_dir 
                         if input_dir 
                         else './trimmed').resolve()
    output_dir = Path(output_dir 
                          if output_dir 
                          else './mapped').resolve()
    
    if not idx_prefix:
        index_dir = Path('./index/grcm38_snp_tran/').resolve()
        idx_prefix = str(index_dir / 'genome_snp_tran') # The / is for appending to the path object.
    
    ram = ram if ram else 8
    
    print( 'Resolved parameters: \n'
          f'    Input directory: {input_dir}\n'
          f'    Output directory: {output_dir}\n'
          f'    Index prefix: {idx_prefix}\n'
          f'    RAM per process: {ram}')
    
    # 1. --- Find the data to map.
    #        The data is in the directory "../RNAseq_data" (a symbolic link to the actual data.)
    #        Here we fetch information of the files containing the data, whether they are paired 
    #        and their location in the filesystem.
    files = search_files(input_dir)
    
    
    # 2. --- Generate the mapping commands.
    #        From the information of the files, generate the commands
    #        needed.
    
    commands = list(assemble_commands(files,
                                      idx_prefix,
                                      output_dir))
    
    
    # 3. --- Assemble the mapping script.
    #        Create the script that will launch the paralell jobs.
    python3_exec_path = get_output('which python3')
    
    # We want every command to be associated to a job id.
    # (we add one to i because job ids start from 1) 
    commands_str = "\n    ".join( f"commands[{i+1}]='{s}'" 
                                  for i,s in enumerate(commands) )
    
    # vvvvvv This is the script to be generated
    script_contents = f"""\
    #! {python3_exec_path}
    
    # Run through this shell
    #$ -S {python3_exec_path}
    
    # Use current working directory
    #$ -cwd
    
    # Join stdout and stderr
    #$ -j y
    
    # If modules are needed, source modules environment (Do not delete the next line):
    #. /etc/profile.d/modules.sh
    
    # Name the job array
    #$ -N rnaseq_map
    
    # Pass environment
    #$ -V
    
    # Specify available RAM per process, per core.
    #$ -l vf={ram}G
    
    # Use as many jobs as needed
    #$ -t 1-{len(commands)}
    
    
    '''
    
    Paralell mapping jobs
    ---------------------
    
    The current script was autogenerated with the 
    file `script.rnaseq_map.py`, look there for documentation.

    '''
    import os
    import subprocess
    import maya
    from pathlib import Path
    
    
    # The commands to be executed
    commands = dict()
    {commands_str}
    
    # Fetch the job id
    task_id = int( os.environ['SGE_TASK_ID'] )
    
    # Fetch the command corresponding to the current job
    command = commands[task_id]
    
    # Get the name of the output file for the current job
    output_file = command.split()[command.split().index("-S") + 1]
    
    # Execute the job
    if Path(output_file).exists():
        print(f'Task {{task_id}}. Output file already exists:', output_file, flush=True)
    
    else:
        print(f'Task {{task_id}}. Executing command @', maya.now(), ':', command, flush=True)

        subprocess.run(command.split()) # <-- Here it is executed, splitting is 
                                        #     necessary to pass the arguments 
                                        #     appropriately                            
        print(f'Task {{task_id}}. Finished execution @', maya.now(), flush=True)
    """
    # Remove indentation
    script_contents = textwrap.dedent(script_contents)



    # 4. --- Write the mapping script to a file.

    script_name = 'script.autogenerated.rnaseq_map_jobs.py'

    with open(script_name, 'w') as outf:
        outf.write(script_contents)



    # 5. --- Execute the script

    run(f"qsub {script_name}")
# ---



if __name__ == '__main__':
    # Command line interface
    main()
