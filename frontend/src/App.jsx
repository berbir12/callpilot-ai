import React, { useState, useEffect, useCallback } from 'react';
import LandingPage from './components/LandingPage';
import ServiceSelection from './components/ServiceSelection';
import TimeWindowSelector from './components/TimeWindowSelector';
import PreferencesPanel from './components/PreferencesPanel';
import SwarmVisualization from './components/SwarmVisualization';
import ResultsPanel from './components/ResultsPanel';
import ConfirmationCard from './components/ConfirmationCard';
import LocationPicker from './components/LocationPicker';
import { startSwarm } from './services/swarmService';
import './styles/App.css';

const VIEWS = {
  LANDING: 'landing',
  INPUT: 'input',
  SWARM: 'swarm',
  RESULTS: 'results',
  CONFIRMATION: 'confirmation',
};

function App() {
  const [currentView, setCurrentView] = useState(VIEWS.LANDING);
  const [formData, setFormData] = useState({
    service: 'dentist',
    time_window: null,
    preferences: {
      time_weight: 0.5,
      rating_weight: 0.3,
      distance_weight: 0.2,
    },
  });
  const [location, setLocation] = useState(null); // { lat, lng }
  const [providers, setProviders] = useState([]);
  const [swarmResults, setSwarmResults] = useState([]);
  const [rankedResults, setRankedResults] = useState([]);
  const [bestResult, setBestResult] = useState(null);
  const [isSwarmActive, setIsSwarmActive] = useState(false);
  const [error, setError] = useState(null);
  const [busySlots, setBusySlots] = useState([]);
  const [selectedAppointment, setSelectedAppointment] = useState(null);

  // Load busy slots from calendar (graceful if backend returns 500 or is down)
  useEffect(() => {
    const loadBusySlots = async () => {
      try {
        const response = await fetch('/data/calendar.json');
        let data = {};
        if (response.ok) {
          try {
            data = await response.json();
          } catch {
            // non-JSON response
          }
        }
        setBusySlots(data.user_calendar?.busy_slots || []);
      } catch (e) {
        console.warn('Could not load calendar data:', e);
        setBusySlots([]);
      }
    };
    loadBusySlots();
  }, []);

  const handleStartDemo = () => {
    setCurrentView(VIEWS.INPUT);
    setError(null);
  };

  const handleServiceChange = (service) => {
    setFormData((prev) => ({ ...prev, service }));
  };

  const handleTimeWindowChange = useCallback((timeWindow) => {
    setFormData((prev) => ({ ...prev, time_window: timeWindow }));
  }, []);

  const handlePreferencesChange = useCallback((preferences) => {
    setFormData((prev) => ({ ...prev, preferences }));
  }, []);

  const handleStartSwarm = async () => {
    setError(null);
    setIsSwarmActive(true);
    setSwarmResults([]);
    setRankedResults([]);
    setBestResult(null);
    setCurrentView(VIEWS.SWARM);

    try {
      const payload = {
        service: formData.service,
        time_window: formData.time_window,
        preferences: formData.preferences,
        limit: 5, // Limit to 5 providers for demo
        ...(location && { lat: location.lat, lng: location.lng }),
      };

      const results = [];

      await startSwarm(payload, {
        onStart: (event) => {
          console.log('Swarm started:', event);
          // Populate providers immediately from the start event
          if (event.providers && event.providers.length > 0) {
            setProviders(event.providers);
          }
        },
        onProgress: (result) => {
          // Add or update result
          setSwarmResults((prev) => {
            const existing = prev.findIndex(
              (r) => r.provider?.name === result.provider?.name
            );
            if (existing >= 0) {
              const updated = [...prev];
              updated[existing] = result;
              return updated;
            }
            return [...prev, result];
          });
        },
        onComplete: (event) => {
          setIsSwarmActive(false);
          if (event.error) setError(event.error);
          setRankedResults(event.ranked || []);
          setBestResult(event.best || null);
          setCurrentView(VIEWS.RESULTS);
        },
        onError: (err) => {
          setIsSwarmActive(false);
          setError(err?.message || 'An error occurred during the swarm call. Please try again.');
          console.error('Swarm error:', err);
          // Show results even if there were errors, if we have any
          if (swarmResults.length > 0) {
            setCurrentView(VIEWS.RESULTS);
          }
        },
      });
    } catch (err) {
      setIsSwarmActive(false);
      setError(err?.message || 'Failed to start swarm. Please check your connection and try again.');
      console.error('Swarm error:', err);
      setCurrentView(VIEWS.INPUT);
    }
  };

  const handleSelectAppointment = (appointment) => {
    setSelectedAppointment(appointment);
    setCurrentView(VIEWS.CONFIRMATION);
  };

  const handleConfirmBooking = (appointment) => {
    // In a real app, this would send a confirmation to the backend
    console.log('Booking confirmed:', appointment);
    // Could show a success message or redirect
  };

  const handleBackToStart = () => {
    setCurrentView(VIEWS.LANDING);
    setFormData({
      service: 'dentist',
      time_window: null,
      preferences: {
        time_weight: 0.5,
        rating_weight: 0.3,
        distance_weight: 0.2,
      },
    });
    setLocation(null);
    setSwarmResults([]);
    setRankedResults([]);
    setBestResult(null);
    setSelectedAppointment(null);
    setError(null);
  };

  const handleBackToResults = () => {
    setCurrentView(VIEWS.RESULTS);
    setSelectedAppointment(null);
  };

  // Get providers from results for visualization
  useEffect(() => {
    if (swarmResults.length > 0) {
      const providerList = swarmResults.map((r) => r.provider).filter(Boolean);
      setProviders(providerList);
    }
  }, [swarmResults]);

  return (
    <div className="app">
      {currentView === VIEWS.LANDING && (
        <LandingPage onStartDemo={handleStartDemo} />
      )}

      {currentView === VIEWS.INPUT && (
        <div className="input-view">
          <div className="input-container">
            <h1>Book Your Appointment</h1>
            <p className="input-subtitle">
              Fill in your preferences and let AI find the best match
            </p>

            <div className="input-form">
              <ServiceSelection
                value={formData.service}
                onChange={handleServiceChange}
              />

              <LocationPicker
                value={location}
                onChange={setLocation}
              />

              <TimeWindowSelector
                value={formData.time_window}
                onChange={handleTimeWindowChange}
                busySlots={busySlots}
              />

              <PreferencesPanel
                value={formData.preferences}
                onChange={handlePreferencesChange}
              />

              {error && (
                <div className="error-banner">
                  {error}
                </div>
              )}

              <div className="form-actions">
                <button
                  className="back-button"
                  onClick={handleBackToStart}
                >
                  Back
                </button>
                <button
                  className="start-swarm-button"
                  onClick={handleStartSwarm}
                  disabled={!formData.time_window || !location}
                >
                  Start Swarm Call
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {currentView === VIEWS.SWARM && (
        <div className="swarm-view">
          <div className="swarm-container">
            <button
              className="back-button-top"
              onClick={() => {
                setIsSwarmActive(false);
                setCurrentView(VIEWS.INPUT);
              }}
            >
              ← Back
            </button>
            <SwarmVisualization
              providers={providers}
              results={swarmResults}
              isActive={isSwarmActive}
            />
            {error && (
              <div className="error-banner">
                {error}
              </div>
            )}
          </div>
        </div>
      )}

      {currentView === VIEWS.RESULTS && (
        <div className="results-view">
          <div className="results-container">
            <button
              className="back-button-top"
              onClick={handleBackToStart}
            >
              ← Start Over
            </button>
            <ResultsPanel
              ranked={rankedResults}
              best={bestResult}
              onSelect={handleSelectAppointment}
            />
          </div>
        </div>
      )}

      {currentView === VIEWS.CONFIRMATION && selectedAppointment && (
        <div className="confirmation-view">
          <div className="confirmation-container">
            <button
              className="back-button-top"
              onClick={handleBackToResults}
            >
              ← Back to Results
            </button>
            <ConfirmationCard
              appointment={selectedAppointment}
              onConfirm={handleConfirmBooking}
              onCancel={handleBackToResults}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
