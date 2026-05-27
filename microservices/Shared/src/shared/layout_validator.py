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
from shared.gerritmodel import known_events, known_labels

class Validator:
    @classmethod
    def getYamlData(cls,file_name : str , dir_path : str) -> dict:
        file_path = os.path.join(dir_path , file_name)
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
    def createJobsSchema(cls, nodeset_names: set = None):
        nodeset_validator = (
            V.In(nodeset_names, msg="nodeset not defined in nodesets.yaml")
            if nodeset_names
            else str
        )
        job_detail_schema = {
            V.Required('name'): str,
            V.Required('nodeset'): nodeset_validator,
            V.Optional('timeout'): int,
            V.Optional('pre-run'): V.Any(str, [str]),
            V.Required('run'): V.Any(str, [str]),
            V.Optional('post-run'): V.Any(str, [str]),
        }
        jobs_file_schema = V.Schema({
            V.Required('jobs'): [
                {V.Required('job'): job_detail_schema}
            ]
        })
        return jobs_file_schema

    @classmethod
    def createNodesetsSchema(cls):
        node_schema = {
            V.Required('name'): str,
            V.Required('label'): str,
        }
        nodeset_detail_schema = {
            V.Required('name'): str,
            V.Required('nodes'): [node_schema],
        }
        nodesets_file_schema = V.Schema({
            V.Required('nodesets'): [
                {V.Required('nodeset'): nodeset_detail_schema}
            ]
        })
        return nodesets_file_schema

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
            V.Optional('start-message') : V.Any(str, None),
            V.Optional('failure-message') : V.Any(str, None),
            V.Optional("success-message") : V.Any(str, None),
            V.Optional(V.Any('success','failure','start')) : gerrit_pipeline_result
        }
        pipeline_file_schema = V.Schema({
            V.Required('pipelines') : [
                {V.Required('pipeline') : pipeline_detail_schema}
            ]
        })
        return pipeline_file_schema
    @classmethod
    def validate(cls, data: dict, file_name: str, list_of_pipelines: list = None, list_of_jobs: list = None, list_of_nodesets: set = None) -> dict:
        resurce_name = os.path.splitext(file_name)[0]
        resurces = data.get(resurce_name)
        try:
            names = Validator.checkDuplicate(resurces)
            match resurce_name:
                case 'projects':
                    schema = Validator.createProjectSchema(list_of_pipelines, list_of_jobs)
                case 'jobs':
                    schema = Validator.createJobsSchema(nodeset_names=list_of_nodesets)
                case 'pipelines':
                    schema = Validator.createPipelinesSchema()
                case 'nodesets':
                    schema = Validator.createNodesetsSchema()
            schema(data)
            return data, names
        except V.Invalid as E:
            raise V.Invalid(f"{E} in {file_name} file ")
    @classmethod
    def validateAllFiles(cls , dir_path):
        # validation order: nodesets → jobs → pipelines → projects
        try:
            nodesets_data = Validator.getYamlData('nodesets.yaml', dir_path)
            nodesets_data, nodeset_names = Validator.validate(nodesets_data, 'nodesets.yaml')

            jobs_data = Validator.getYamlData('jobs.yaml', dir_path)
            jobs_data, job_names = Validator.validate(jobs_data, 'jobs.yaml', list_of_nodesets=nodeset_names)

            pipelines_data = Validator.getYamlData('pipelines.yaml', dir_path)
            pipelines_data, pipeline_names = Validator.validate(pipelines_data, 'pipelines.yaml')

            projects_data = Validator.getYamlData('projects.yaml', dir_path)
            projects_data, project_names = Validator.validate(
                projects_data, 'projects.yaml',
                list_of_pipelines=pipeline_names,
                list_of_jobs=job_names,
            )

            return {
                "nodesets_data": nodesets_data,
                "nodeset_names": nodeset_names,
                "jobs_data": jobs_data,
                "job_names": job_names,
                "pipelines_data": pipelines_data,
                "pipeline_names": pipeline_names,
                "projects_data": projects_data,
                "projects_names": project_names,
            }

        except Exception:
            raise
