# mypy: disable-error-code=call-arg,arg-type,index
# pyright: reportIndexIssue=false, reportCallIssue=false, reportArgumentType=false

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from nova_model import nova_lite


@CrewBase
class CuratedEmailsCrew:
    """Curated Emails Crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def seasonal_event_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["seasonal_event_agent"],
            llm=nova_lite,
            verbose=True,
        )

    @agent
    def seasonal_event_interpretation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["seasonal_event_interpretation_agent"],
            llm=nova_lite,
            verbose=True,
        )

    @agent
    def seasonal_event_curator_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["seasonal_event_curator_agent"],
            llm=nova_lite,
            verbose=True,
        )

    @agent
    def photo_analysis_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["photo_analysis_agent"],
            llm=nova_lite,
            verbose=True,
        )

    @agent
    def live_camera_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["live_camera_agent"],
            llm=nova_lite,
            verbose=True,
        )

    @agent
    def digest_composer_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["digest_composer_agent"],
            llm=nova_lite,
            verbose=True,
        )

    @task
    def seasonal_event_detection_task(self) -> Task:
        return Task(
            config=self.tasks_config["seasonal_event_detection_task"],
        )

    @task
    def seasonal_event_interpretation_task(self) -> Task:
        return Task(
            config=self.tasks_config["seasonal_event_interpretation_task"],
        )

    @task
    def seasonal_event_curator_task(self) -> Task:
        return Task(
            config=self.tasks_config["seasonal_event_curator_task"],
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
    def city_landmarks_task(self) -> Task:
        return Task(
            config=self.tasks_config["city_landmarks_task"],
        )

    @task
    def compose_digest_task(self) -> Task:
        return Task(
            config=self.tasks_config["compose_digest_task"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
