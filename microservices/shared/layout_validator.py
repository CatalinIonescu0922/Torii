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
        return False
        
    def validateProjectFile(self ,data : dict) -> dict:
        projects = data.get('projects')
        try:
            self.checkDuplicate(projects)
        except V.Invalid as E :
            raise V.Invalid(f"{E} in project.yaml file ")
        # here we know for sure no duplication name are present 
        # check the overwall structure of the file 
        
    def validatePipelineFile(self , data : dict) :

        return None
    
    def validateJobsFile(self ,data : dict):
        return None
    

def main():
    name = 'projects.yaml'
    Parser = ParseYamlFile()
    Parser.getYamlData(name)

if __name__ == '__main__':
    main()