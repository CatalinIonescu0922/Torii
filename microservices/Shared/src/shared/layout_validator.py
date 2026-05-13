# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "voluptuous",
#     "pyyaml",
#     "pydantic"
# ]
# ///

import voluptuous as V
import yaml
import os
import sys
from shared.gerritmodel import known_events, known_labels
from pathlib import Path

class Validator:
    @classmethod
    def get_file_full_path(cls)-> Path:
        main_file = sys.modules['__main__'].__file__
        return Path(main_file).resolve().parent / 'config' / 'layout'

    @classmethod
    def getYamlData(cls,file_name : str) -> dict:
        file_path = Validator.get_file_full_path() / file_name
        try:
            with open(file_path , 'r') as yaml_file:
                yaml_data = yaml.full_load(yaml_file)
            return yaml_data
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Could not find anything at this {file_path} path") from e
        except yaml.YAMLError as e:
            raise yaml.YAMLError("This may not be a yaml file") from e
    @classmethod
    def checkDuplicate(cls, data : list):
        duplicate = []
        seen = set()
        first_key = list(data[0])[0]
        for item in data:
            if item[first_key]['name'] not in seen:
                seen.add(item[first_key]['name'])
            else:
                duplicate.append(item[first_key]['name'])
        if duplicate:
            raise V.Invalid(f"foud this duplicated names {duplicate}")
        return seen
    
    @classmethod
    def createProjectSchema(cls,list_of_pipelines: list , list_of_jobs : list) -> V.Schema:
        event_type = {
                V.Optional('event-type') : [V.In(known_events , msg="the event is not a known event")]
        }
        project_detail_schema = {
        V.Required('name') : str,
        V.Required('branches') : [str],
        V.Required('merge-mode') : V.Any('merge','rebase','cherry-pick'),
        V.Optional(V.In(list_of_pipelines , msg="Pipeline not defined in pipelines yaml file please create the pipeline first")) : {
            V.Required('jobs') : [V.In(list_of_jobs , msg="the job set here is not defined in the jobs file")] 
            }
        }

        projects_file_schema = V.Schema({
            V.Optional('filters') : {
                V.Optional('event-filters') : event_type
            },
            V.Required('projects') : [
                { V.Required('project') : project_detail_schema }
            ]
        })
        return projects_file_schema

    @classmethod
    def createJobsSchema(cls):
        jobs_file_schema = V.Schema({
            V.Required('jobs') : [
                {V.Required('job') : {
                    V.Required('name') : str
                }}
            ]
        })
        return jobs_file_schema

    @classmethod
    def createPipelinesSchema(cls) -> V.Schema:
        approval = {
            V.Optional(V.Any(V.In(known_labels), str)): V.Any(int , [int])
        }
        gerrit_pipeline_result = {
            V.Optional('gerrit') :  [approval]
            
        }
        gerrit_trigger = {
            V.Required('gerrit') : [
                { 
                    V.Required('event') : V.In(known_events , msg='the event is not a known event') ,
                    V.Optional('comment') : [str],
                    V.Optional('branch') : [str],
                    V.Optional('ref') : [str],
                    V.Optional('approval') : [approval],

                 }
            ]
        }
        require_detail_schema = {
            V.Optional('open') : bool,
            V.Optional('current-patchset') : bool,
            V.Optional('approval') : [approval]
        }
        reject_detail_schema = {
            V.Optional('approval') : [approval]
        }
        pipeline_detail_schema = {
            V.Required('name') : str,
            V.Required('manager') : str,
            V.Required('trigger') : gerrit_trigger,
            V.Required('require') : require_detail_schema,
            V.Optional('reject') : reject_detail_schema,
            V.Optional(V.Any('success','failure','start')) : gerrit_pipeline_result
        }
        pipeline_file_schema = V.Schema({
            V.Required('pipelines') : [
                {V.Required('pipeline') : pipeline_detail_schema}
            ]
        })
        return pipeline_file_schema
    @classmethod
    def validate(cls,data : dict, file_name : str, list_of_pipelines:list=None , list_of_jobs:list=None) -> dict:
        # takes only the word before the . of the file_name
        resurce_name = os.path.splitext(file_name)[0]
        resurces = data.get(resurce_name)
        try:
            names = Validator.checkDuplicate(resurces)
            match resurce_name:
                case 'projects':
                    schema = Validator.createProjectSchema(list_of_pipelines , list_of_jobs)
                case 'jobs':
                    schema = Validator.createJobsSchema()
                case 'pipelines':
                    schema = Validator.createPipelinesSchema()
            schema(data)
            return data , names
        except V.Invalid as E :
            raise V.Invalid(f"{E} in {file_name} file ")
    @classmethod
    def validateAllFiles(cls) :
        # the order of the files is like this jobs pipelines then projects 
        try:
            jobs_data = Validator.getYamlData('jobs.yaml')
            jobs_data , job_names = Validator.validate(jobs_data,'jobs.yaml')

            pipelines_data = Validator.getYamlData('pipelines.yaml')
            pipelines_data , pipeline_names = Validator.validate(pipelines_data,'pipelines.yaml')

            projects_data = Validator.getYamlData('projects.yaml')
            projects_data, project_names = Validator.validate(projects_data,'projects.yaml',list_of_pipelines=pipeline_names ,list_of_jobs=job_names)

            return {
                "jobs_data" : jobs_data,
                "job_names" : job_names,
                "pipelines_data" : pipelines_data,
                "pipeline_names" : pipeline_names,
                "projects_data" : projects_data,
                "projects_names" : project_names
            }
            
        except Exception:
            raise 
