# mypy: disable-error-code=call-arg,arg-type,index
# pyright: reportIndexIssue=false, reportCallIssue=false, reportArgumentType=false

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from tools.fetch_local_photos_tool import FetchLocalPhotosTool
from tools.fetch_seasonal_events_tool import FetchSeasonalEventsTool
from nova_model import nova_lite


@CrewBase
class CuratedEmailsCrew:
    """Curated Emails Crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def channel_classifier_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["channel_classifier_agent"],
            llm=nova_lite,
            verbose=True,
        
        )
    @agent
    def event_explanation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["event_explanation_agent"],
            llm=nova_lite,
            verbose=True,
            allow_delegation=True,
        )
    @agent
    def context_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["context_agent"],
            llm=nova_lite,
            verbose=True,
        )
    @agent
    def concept_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["concept_agent"],
            llm=nova_lite,
            verbose=True,
            allow_delegation=True,
        )
    @agent
    def seasonal_event_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["seasonal_event_agent"],
            llm=nova_lite,
            tools=[FetchSeasonalEventsTool()],
            verbose=True,
        )
    @agent
    def photo_analysis_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["photo_analysis_agent"],
            llm=nova_lite,
            verbose=True,
            tools=[FetchLocalPhotosTool()]
        )
    @agent
    def digest_composer_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["digest_composer_agent"],
            llm=nova_lite,
            verbose=True,
            allow_delegation=True,
        )

    @task
    def seasonal_event_detection_task(self) -> Task:
        return Task(
            config=self.tasks_config["seasonal_event_detection_task"],
        )

      
    @task
    def seasonal_event_explanation_task(self) -> Task:
        return Task(
            config=self.tasks_config["seasonal_event_explanation_task"],
        )
    @task
    def classify_channel_task(self) -> Task:
        return Task(
            config=self.tasks_config["classify_channel_task"],
        )
    @task
    def explain_event_task(self) -> Task:
        return Task(
            config=self.tasks_config["explain_event_task"],
        )
    @task
    def generate_context_task(self) -> Task:
        return Task(
            config=self.tasks_config["generate_context_task"],
        )
    @task
    def explain_concepts_task(self) -> Task:
        return Task(
            config=self.tasks_config["explain_concepts_task"],
        )
    @task
    def photo_ranking_task(self) -> Task:
        return Task(
            config=self.tasks_config["photo_ranking_task"],
        )
    @task
    def photo_caption_task(self) -> Task:
        return Task(
            config=self.tasks_config["photo_caption_task"],
        )
    @task
    def compose_digest_task(self) -> Task:
        return Task(
            config=self.tasks_config["compose_digest_task"],
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
