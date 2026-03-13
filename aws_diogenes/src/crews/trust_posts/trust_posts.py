# mypy: disable-error-code=call-arg,arg-type,index
# pyright: reportIndexIssue=false, reportCallIssue=false, reportArgumentType=false

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from nova_model import nova_lite

@CrewBase
class TrustPostsCrew:
    """Trust Posts Crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def post_identity_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["post_identity_agent"],
            llm=nova_lite,
            verbose=True,
        
        )
    @agent
    def post_summary_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["post_summary_agent"],
            llm=nova_lite,
            verbose=True,
        )
    

    @task
    def verify_contact_task(self) -> Task:
        return Task(
            config=self.tasks_config["verify_contact_task"],
        )

      
    @task
    def summarize_post_task(self) -> Task:
        return Task(
            config=self.tasks_config["summarize_post_task"],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the posts Crew"""


        return Crew(
            agents=self.agents,  
            tasks=self.tasks,  
            process=Process.sequential,
            verbose=True,
        )
