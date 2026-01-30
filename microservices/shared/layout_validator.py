# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "voluptuous",
#     "pyyaml",
# ]
# ///

import voluptuous as V
import yaml
class ParseYamlFile:
    # define schema available across all of the layouts

    # base schemas used across all of the generating files 

    def validatePipelinesInLayout()-> dict:
        return None 
    def createProjectSchema(self,list_of_pipelines: list , list_of_jobs : list , known_events : list) -> V.Schema:
        event_type = {
                V.Optional('event-type') : [V.In(known_events)]
        }
        project_detail_schema = {
        V.Required('name') : str,
        V.Required('branches') : [str],
        V.Required('merge-mode') : V.Any('merge','rebase','cherry-pick'),
        V.Optional(V.In(list_of_pipelines)) : {
            V.Required('jobs') : [V.In(list_of_jobs)] 
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
    
    def getYamlData(self,file_name : str) -> dict:
        try:
            with open(file_name , 'r') as yaml_file:
                yaml_data = yaml.full_load(yaml_file)
            return self.validateFile(file_name , yaml_data)
        except FileNotFoundError :
            print("the file was not found")
        except yaml.YAMLError as e:
            print(f'This may not be a yaml file. {e}')
    # should raise exceptions regarding what is missing 
    def validateFile(self , file_name : str , data : dict):
        handler_validate = {
            'projects.yaml'  :self.validateProjectFile,
            'pipelines.yaml' :self.validatePipelineFile,
            'jobs.yaml'      :self.validateJobsFile 

        }
        validate = handler_validate[file_name]
        try:
            # in case of the file passing the validation 
            # will return the data 
            return validate(data)
        except Exception as e:
            raise e

    def checkDuplicate(self , data : list):
        # we know that here we receive a list of dict with the same first key
        # the value of the first key is all of the properties of the data beeing send 
        # this will only raise if a duplicate if found
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
          
    def validateProjectFile(self ,data : dict) -> dict:
        projects = data.get('projects')
        try:
            self.checkDuplicate(projects)
            schema = self.createProjectSchema(['check' , 'gate'] , ['check-syntax', 'unit-tests','integration-tests'],['reviewer-added', 'ref-updated'])
            schema(data)
        except V.Invalid as E :
            raise V.Invalid(f"{E} in projects.yaml file ")
        # here we know for sure no duplication name are present 
        # check the overwall structure of the file 
        
    def validatePipelineFile(self , data : dict) :

        return None
    
    def validateJobsFile(self ,data : dict):
        return None
    

def main():
    names = ['projects.yaml' , 'pipelines.yaml' , 'jobs.yaml']
    Parser = ParseYamlFile()
    Parser.getYamlData(names[0])

if __name__ == '__main__':
    main()
