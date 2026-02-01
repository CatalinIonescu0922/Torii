# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "voluptuous",
#     "pyyaml",
# ]
# ///

import voluptuous as V
import yaml
import os
from model import known_events , known_labels


class Validator:
    def getYamlData(self,file_name : str) -> dict:
        try:
            with open(file_name , 'r') as yaml_file:
                yaml_data = yaml.full_load(yaml_file)
            return yaml_data
        except FileNotFoundError :
            print("the file was not found")
        except yaml.YAMLError as e:
            print(f'This may not be a yaml file. {e}')
    def checkDuplicate(self , data : list):
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
    
    def createProjectSchema(self,list_of_pipelines: list , list_of_jobs : list) -> V.Schema:
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

    def createJobsSchema(self):
        jobs_file_schema = V.Schema({
            V.Required('jobs') : [
                {V.Required('job') : {
                    V.Required('name') : str
                }}
            ]
        })
        return jobs_file_schema

    def createPipelinesSchema(self) -> V.Schema:
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
    def validate(self ,data : dict, file_name : str, list_of_pipelines:list=None , list_of_jobs:list=None) -> dict:
        # takes only the word before the . of the file_name
        resurce_name = os.path.splitext(file_name)[0]
        resurces = data.get(resurce_name)
        try:
            names = self.checkDuplicate(resurces)
            match resurce_name:
                case 'projects':
                    schema = self.createProjectSchema(list_of_pipelines , list_of_jobs)
                case 'jobs':
                    schema = self.createJobsSchema()
                case 'pipelines':
                    schema = self.createPipelinesSchema()
            schema(data)
            return data , names
        except V.Invalid as E :
            raise V.Invalid(f"{E} in {file_name} file ")
    def validateAllFiles(self) :
        # the order of the files is like this jobs pipelines then projects 
        try:
            jobs_data = self.getYamlData('jobs.yaml')
            jobs_data , job_names = self.validate(jobs_data,'jobs.yaml')

            pipelines_data = self.getYamlData('pipelines.yaml')
            pipelines_data , pipeline_names = self.validate(pipelines_data,'pipelines.yaml')

            projects_data = self.getYamlData('projects.yaml')
            projects_data, project_names = self.validate(projects_data,'projects.yaml',list_of_pipelines=pipeline_names ,list_of_jobs=job_names)

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

def main():
    Validatorul = Validator()
    Validatorul.validateAllFiles()
    # the names of the yaml files 

if __name__ == '__main__':
    main()
